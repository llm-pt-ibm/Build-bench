%global debug_package %{nil}
Name:           ck-acceptance
Version:        1
Release:        0
Summary:        Acceptance test of ck for Build-bench
License:        MIT
Source0:        expected-disturl
Source1:       common.h
Source2:       barrier_centralized.c
Source3:       barrier_combining.c
Source4:       barrier_dissemination.c
Source5:       barrier_tournament.c
Source6:       barrier_mcs.c
BuildRequires:  ck-devel
BuildRequires:  gcc

%description
Builds only when the ck under test works: the five barrier validation programs of ck's regressions, built against the installed library, finish.

%prep
%setup -q -c -T
cp %{SOURCE0} %{SOURCE1} %{SOURCE2} %{SOURCE3} %{SOURCE4} %{SOURCE5} %{SOURCE6} .

%build
# the build under test, not an older one of the distribution
disturl=$(rpm -q --qf '%%{DISTURL}\n' --whatprovides 'libck0' | head -1)
grep -qxF "$disturl" expected-disturl || { echo "Check failed: libck0 comes from $disturl, not from the build under test"; exit 1; }
n=$(nproc); [ "$n" -gt 4 ] && n=4; [ "$n" -lt 2 ] && n=2
for t in centralized combining dissemination tournament mcs; do
  gcc -O2 -pthread -D_GNU_SOURCE -DCORES=$n -I/usr/include/ck -o barrier_$t barrier_$t.c -lck
  echo "barrier_$t with $n threads"
  timeout 600 ./barrier_$t $n 1 1 || { echo "Check failed: barrier_$t did not finish (status $?)"; exit 1; }
done

%install
mkdir -p %{buildroot}%{_datadir}/%{name}
echo passed > %{buildroot}%{_datadir}/%{name}/result

%files
%{_datadir}/%{name}

%changelog

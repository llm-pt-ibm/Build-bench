%global debug_package %{nil}
Name:           CalcMySky-acceptance
Version:        1
Release:        0
Summary:        Acceptance test of CalcMySky for Build-bench
License:        MIT
Source0:        expected-disturl
BuildRequires:  CalcMySky
BuildRequires:  libShowMySky-Qt6-15

%description
Builds only when the CalcMySky under test works: its programs and library load and calcmysky answers --help.

%prep
%setup -q -c -T
cp %{SOURCE0} .

%build
# the build under test, not an older one of the distribution
disturl=$(rpm -q --qf '%%{DISTURL}\n' --whatprovides 'CalcMySky' | head -1)
grep -qxF "$disturl" expected-disturl || { echo "Check failed: CalcMySky comes from $disturl, not from the build under test"; exit 1; }
for f in /usr/bin/calcmysky /usr/bin/showmysky /usr/%{_lib}/libShowMySky-Qt6.so.15*; do
  if ldd "$f" | grep 'not found'; then echo "Check failed: $f misses libraries"; exit 1; fi
done
QT_QPA_PLATFORM=offscreen calcmysky --help > help.txt 2>&1 || true
cat help.txt
grep -qi -E 'usage|options' help.txt || { echo "Check failed: calcmysky --help printed no usage"; exit 1; }

%install
mkdir -p %{buildroot}%{_datadir}/%{name}
echo passed > %{buildroot}%{_datadir}/%{name}/result

%files
%{_datadir}/%{name}

%changelog

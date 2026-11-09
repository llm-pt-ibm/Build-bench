%global debug_package %{nil}
Name:           tail-tray-acceptance
Version:        1
Release:        0
Summary:        Acceptance test of tail-tray for Build-bench
License:        MIT
Source0:        expected-disturl
BuildRequires:  tail-tray

%description
Builds only when the tail-tray under test works: tail-tray and its libraries load.

%prep
%setup -q -c -T
cp %{SOURCE0} .

%build
# the build under test, not an older one of the distribution
disturl=$(rpm -q --qf '%%{DISTURL}\n' --whatprovides 'tail-tray' | head -1)
grep -qxF "$disturl" expected-disturl || { echo "Check failed: tail-tray comes from $disturl, not from the build under test"; exit 1; }
for f in /usr/bin/tail-tray; do
  if ldd "$f" | grep 'not found'; then echo "Check failed: $f misses libraries"; exit 1; fi
done

%install
mkdir -p %{buildroot}%{_datadir}/%{name}
echo passed > %{buildroot}%{_datadir}/%{name}/result

%files
%{_datadir}/%{name}

%changelog

%global debug_package %{nil}
Name:           doomsday-acceptance
Version:        1
Release:        0
Summary:        Acceptance test of doomsday for Build-bench
License:        MIT
Source0:        expected-disturl
BuildRequires:  doomsday

%description
Builds only when the doomsday under test works: its programs and libraries load and doomsday answers --version.

%prep
%setup -q -c -T
cp %{SOURCE0} .

%build
# the build under test, not an older one of the distribution
disturl=$(rpm -q --qf '%%{DISTURL}\n' --whatprovides 'doomsday' | head -1)
grep -qxF "$disturl" expected-disturl || { echo "Check failed: doomsday comes from $disturl, not from the build under test"; exit 1; }
for f in $(rpm -ql doomsday | grep -E '^/usr/bin/|/usr/%{_lib}/.*[.]so'); do
  if ldd "$f" | grep 'not found'; then echo "Check failed: $f misses libraries"; exit 1; fi
done
QT_QPA_PLATFORM=offscreen SDL_VIDEODRIVER=dummy timeout 60 doomsday --version > version.txt 2>&1 || true
cat version.txt
grep -q '2\.3' version.txt || { echo "Check failed: doomsday --version"; exit 1; }

%install
mkdir -p %{buildroot}%{_datadir}/%{name}
echo passed > %{buildroot}%{_datadir}/%{name}/result

%files
%{_datadir}/%{name}

%changelog

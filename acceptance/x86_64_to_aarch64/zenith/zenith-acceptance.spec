%global debug_package %{nil}
Name:           zenith-acceptance
Version:        1
Release:        0
Summary:        Acceptance test of zenith for Build-bench
License:        MIT
Source0:        expected-disturl
BuildRequires:  zenith

%description
Builds only when the zenith under test works: zenith answers --version.

%prep
%setup -q -c -T
cp %{SOURCE0} .

%build
# the build under test, not an older one of the distribution
disturl=$(rpm -q --qf '%%{DISTURL}\n' --whatprovides 'zenith' | head -1)
grep -qxF "$disturl" expected-disturl || { echo "Check failed: zenith comes from $disturl, not from the build under test"; exit 1; }
zenith --version > version.txt 2>&1 || { cat version.txt; echo "Check failed: zenith --version"; exit 1; }
cat version.txt
grep -q '0\.15' version.txt || { echo "Check failed: zenith --version printed another version"; exit 1; }

%install
mkdir -p %{buildroot}%{_datadir}/%{name}
echo passed > %{buildroot}%{_datadir}/%{name}/result

%files
%{_datadir}/%{name}

%changelog

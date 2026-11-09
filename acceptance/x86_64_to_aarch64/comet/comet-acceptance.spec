%global debug_package %{nil}
Name:           comet-acceptance
Version:        1
Release:        0
Summary:        Acceptance test of comet for Build-bench
License:        MIT
Source0:        expected-disturl
BuildRequires:  comet

%description
Builds only when the comet under test works: comet answers --help.

%prep
%setup -q -c -T
cp %{SOURCE0} .

%build
# the build under test, not an older one of the distribution
disturl=$(rpm -q --qf '%%{DISTURL}\n' --whatprovides 'comet' | head -1)
grep -qxF "$disturl" expected-disturl || { echo "Check failed: comet comes from $disturl, not from the build under test"; exit 1; }
comet --help > help.txt 2>&1 || { cat help.txt; echo "Check failed: comet --help"; exit 1; }
cat help.txt
grep -qi usage help.txt || { echo "Check failed: comet --help printed no usage"; exit 1; }

%install
mkdir -p %{buildroot}%{_datadir}/%{name}
echo passed > %{buildroot}%{_datadir}/%{name}/result

%files
%{_datadir}/%{name}

%changelog

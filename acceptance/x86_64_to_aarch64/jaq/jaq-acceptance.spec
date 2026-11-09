%global debug_package %{nil}
Name:           jaq-acceptance
Version:        1
Release:        0
Summary:        Acceptance test of jaq for Build-bench
License:        MIT
Source0:        expected-disturl
BuildRequires:  jaq

%description
Builds only when the jaq under test works: jaq evaluates a few filters.

%prep
%setup -q -c -T
cp %{SOURCE0} .

%build
# the build under test, not an older one of the distribution
disturl=$(rpm -q --qf '%%{DISTURL}\n' --whatprovides 'jaq' | head -1)
grep -qxF "$disturl" expected-disturl || { echo "Check failed: jaq comes from $disturl, not from the build under test"; exit 1; }
check() { out=$(eval "$1"); [ "$out" = "$2" ] || { echo "Check failed: $1 gave '$out', not '$2'"; exit 1; }; }
check "echo '{\"a\": 1}' | jaq .a" 1
check "jaq -n '[range(5)] | add'" 10
check "echo '[3, 1, 2]' | jaq -c sort" '[1,2,3]'
check "jaq -n '\"a,b,c\" | split(\",\") | length'" 3
check "echo '[1, 5, 2]' | jaq -c 'map(select(. > 1))'" '[5,2]'
check "jaq -rn '\"x\" * 3'" xxx

%install
mkdir -p %{buildroot}%{_datadir}/%{name}
echo passed > %{buildroot}%{_datadir}/%{name}/result

%files
%{_datadir}/%{name}

%changelog

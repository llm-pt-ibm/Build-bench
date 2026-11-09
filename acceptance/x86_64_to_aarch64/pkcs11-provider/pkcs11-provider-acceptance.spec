%global debug_package %{nil}
Name:           pkcs11-provider-acceptance
Version:        1
Release:        0
Summary:        Acceptance test of pkcs11-provider for Build-bench
License:        MIT
Source0:        expected-disturl
BuildRequires:  pkcs11-provider
BuildRequires:  openssl

%description
Builds only when the pkcs11-provider under test works: openssl loads the pkcs11 provider.

%prep
%setup -q -c -T
cp %{SOURCE0} .

%build
# the build under test, not an older one of the distribution
disturl=$(rpm -q --qf '%%{DISTURL}\n' --whatprovides 'pkcs11-provider' | head -1)
grep -qxF "$disturl" expected-disturl || { echo "Check failed: pkcs11-provider comes from $disturl, not from the build under test"; exit 1; }
openssl list -providers -provider pkcs11 -provider default > providers.txt 2>&1 || { cat providers.txt; echo "Check failed: openssl could not load the pkcs11 provider"; exit 1; }
cat providers.txt
grep -qi pkcs11 providers.txt || { echo "Check failed: the pkcs11 provider is not listed"; exit 1; }

%install
mkdir -p %{buildroot}%{_datadir}/%{name}
echo passed > %{buildroot}%{_datadir}/%{name}/result

%files
%{_datadir}/%{name}

%changelog

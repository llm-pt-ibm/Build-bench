%global debug_package %{nil}
Name:           ghc-blake3-acceptance
Version:        1
Release:        0
Summary:        Acceptance test of ghc-blake3 for Build-bench
License:        MIT
Source0:        expected-disturl
Source1:       Main.hs
BuildRequires:  ghc-blake3-devel
BuildRequires:  ghc-ram-devel
BuildRequires:  ghc-tasty-devel
BuildRequires:  ghc-tasty-hunit-devel

%description
Builds only when the ghc-blake3 under test works: the test suite of the blake3 package (test vectors, keys, hashers), built against the installed library, passes.

%prep
%setup -q -c -T
cp %{SOURCE0} %{SOURCE1} .

%build
# the build under test, not an older one of the distribution
disturl=$(rpm -q --qf '%%{DISTURL}\n' --whatprovides 'ghc-blake3' | head -1)
grep -qxF "$disturl" expected-disturl || { echo "Check failed: ghc-blake3 comes from $disturl, not from the build under test"; exit 1; }
ghc -O0 -package blake3 -package ram -package tasty -package tasty-hunit -o blake3-test Main.hs
./blake3-test || { echo "Check failed: the blake3 test suite"; exit 1; }

%install
mkdir -p %{buildroot}%{_datadir}/%{name}
echo passed > %{buildroot}%{_datadir}/%{name}/result

%files
%{_datadir}/%{name}

%changelog

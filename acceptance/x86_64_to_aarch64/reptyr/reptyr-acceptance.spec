%global debug_package %{nil}
Name:           reptyr-acceptance
Version:        1
Release:        0
Summary:        Acceptance test of reptyr for Build-bench
License:        MIT
Source0:        expected-disturl
Source1:       basic.py
Source2:       tty-steal.py
Source3:       util.py
Source4:       victim.c
BuildRequires:  reptyr
BuildRequires:  gcc
BuildRequires:  python3-pexpect
BuildRequires:  python3-python-prctl

%description
Builds only when the reptyr under test works: reptyr's own tests (attaching a running program to a new terminal) pass with the installed reptyr.

%prep
%setup -q -c -T
cp %{SOURCE0} %{SOURCE1} %{SOURCE2} %{SOURCE3} %{SOURCE4} .

%build
# the build under test, not an older one of the distribution
disturl=$(rpm -q --qf '%%{DISTURL}\n' --whatprovides 'reptyr' | head -1)
grep -qxF "$disturl" expected-disturl || { echo "Check failed: reptyr comes from $disturl, not from the build under test"; exit 1; }
mkdir test
cp basic.py tty-steal.py util.py victim.c test/
gcc -o test/victim test/victim.c
ln -s /usr/bin/reptyr reptyr
python3 test/basic.py || { echo "Check failed: reptyr's basic test"; exit 1; }
python3 test/tty-steal.py || { echo "Check failed: reptyr's tty-steal test"; exit 1; }

%install
mkdir -p %{buildroot}%{_datadir}/%{name}
echo passed > %{buildroot}%{_datadir}/%{name}/result

%files
%{_datadir}/%{name}

%changelog

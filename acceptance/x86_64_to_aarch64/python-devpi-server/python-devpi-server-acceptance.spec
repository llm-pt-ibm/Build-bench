%global debug_package %{nil}
Name:           python-devpi-server-acceptance
Version:        1
Release:        0
Summary:        Acceptance test of python-devpi-server for Build-bench
License:        MIT
Source0:        expected-disturl
BuildRequires:  python3-devpi-server

%description
Builds only when the python-devpi-server under test works: devpi-server starts and answers its API.

%prep
%setup -q -c -T
cp %{SOURCE0} .

%build
# the build under test, not an older one of the distribution
disturl=$(rpm -q --qf '%%{DISTURL}\n' --whatprovides 'python3-devpi-server' | head -1)
grep -qxF "$disturl" expected-disturl || { echo "Check failed: python3-devpi-server comes from $disturl, not from the build under test"; exit 1; }
python3 -c 'import devpi_server; print(devpi_server.__version__)'
devpi-init --serverdir "$PWD/srv"
devpi-server --serverdir "$PWD/srv" --host 127.0.0.1 --port 3141 > server.log 2>&1 &
pid=$!
api() { python3 -c "import json, sys, urllib.request; sys.exit(0 if 'result' in json.load(urllib.request.urlopen('http://127.0.0.1:3141/+api', timeout=5)) else 1)"; }
for i in $(seq 60); do api 2>/dev/null && break; sleep 2; done
api || { tail -40 server.log; kill $pid; echo "Check failed: devpi-server did not answer"; exit 1; }
kill $pid

%install
mkdir -p %{buildroot}%{_datadir}/%{name}
echo passed > %{buildroot}%{_datadir}/%{name}/result

%files
%{_datadir}/%{name}

%changelog

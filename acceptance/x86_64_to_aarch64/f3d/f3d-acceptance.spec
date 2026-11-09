%global debug_package %{nil}
Name:           f3d-acceptance
Version:        1
Release:        0
Summary:        Acceptance test of f3d for Build-bench
License:        MIT
Source0:        expected-disturl
BuildRequires:  f3d
BuildRequires:  libvtk-9_7-1
BuildRequires:  python3-vtk

%description
Builds only when the f3d under test works: f3d answers --version and lists its readers.

%prep
%setup -q -c -T
cp %{SOURCE0} .

%build
# the build under test, not an older one of the distribution
disturl=$(rpm -q --qf '%%{DISTURL}\n' --whatprovides 'f3d' | head -1)
grep -qxF "$disturl" expected-disturl || { echo "Check failed: f3d comes from $disturl, not from the build under test"; exit 1; }
f3d --version > version.txt 2>&1 || { cat version.txt; echo "Check failed: f3d --version"; exit 1; }
cat version.txt
grep -q '3\.5' version.txt || { echo "Check failed: f3d --version printed another version"; exit 1; }
f3d --list-readers > readers.txt 2>&1 || { cat readers.txt; echo "Check failed: f3d --list-readers"; exit 1; }
grep -qi -E 'obj|stl' readers.txt || { cat readers.txt; echo "Check failed: f3d lists no OBJ or STL reader"; exit 1; }

%install
mkdir -p %{buildroot}%{_datadir}/%{name}
echo passed > %{buildroot}%{_datadir}/%{name}/result

%files
%{_datadir}/%{name}

%changelog

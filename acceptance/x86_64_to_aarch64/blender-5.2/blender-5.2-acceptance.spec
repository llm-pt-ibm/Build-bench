%global debug_package %{nil}
Name:           blender-5.2-acceptance
Version:        1
Release:        0
Summary:        Acceptance test of blender-5.2 for Build-bench
License:        MIT
Source0:        expected-disturl
BuildRequires:  blender-5.2
BuildRequires:  audaspace-plugin-sdl3
BuildRequires:  audaspace-plugin-sndfile

%description
Builds only when the blender-5.2 under test works: blender renders the default cube with Cycles on the CPU.

%prep
%setup -q -c -T
cp %{SOURCE0} .

%build
# the build under test, not an older one of the distribution
disturl=$(rpm -q --qf '%%{DISTURL}\n' --whatprovides 'blender-5.2' | head -1)
grep -qxF "$disturl" expected-disturl || { echo "Check failed: blender-5.2 comes from $disturl, not from the build under test"; exit 1; }
cat > render.py <<'EOF'
import os, bpy
scene = bpy.context.scene
scene.render.engine = "CYCLES"
scene.cycles.device = "CPU"
scene.cycles.samples = 4
scene.render.resolution_x = scene.render.resolution_y = 32
scene.render.filepath = os.path.join(os.getcwd(), "cube.png")
bpy.ops.render.render(write_still=True)
print("RENDERED", bpy.app.version_string)
EOF
/usr/bin/blender-5.2 -b --factory-startup --python render.py > blender.log 2>&1 || { tail -40 blender.log; echo "Check failed: blender could not render"; exit 1; }
grep -q '^RENDERED 5\.2' blender.log && test -s cube.png || { tail -40 blender.log; echo "Check failed: no render of the default cube"; exit 1; }

%install
mkdir -p %{buildroot}%{_datadir}/%{name}
echo passed > %{buildroot}%{_datadir}/%{name}/result

%files
%{_datadir}/%{name}

%changelog

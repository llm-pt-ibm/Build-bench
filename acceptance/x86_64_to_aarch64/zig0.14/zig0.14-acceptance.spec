%global debug_package %{nil}
Name:           zig0.14-acceptance
Version:        1
Release:        0
Summary:        Acceptance test of zig0.14 for Build-bench
License:        MIT
Source0:        expected-disturl
BuildRequires:  zig0.14

%description
Builds only when the zig0.14 under test works: zig builds and runs a Zig and a C program.

%prep
%setup -q -c -T
cp %{SOURCE0} .

%build
# the build under test, not an older one of the distribution
disturl=$(rpm -q --qf '%%{DISTURL}\n' --whatprovides 'zig0.14' | head -1)
grep -qxF "$disturl" expected-disturl || { echo "Check failed: zig0.14 comes from $disturl, not from the build under test"; exit 1; }
export ZIG_GLOBAL_CACHE_DIR="$PWD/zig-cache" ZIG_LOCAL_CACHE_DIR="$PWD/zig-local"
zig version > version.txt
cat version.txt
grep -q '^0\.14' version.txt || { echo "Check failed: zig version"; exit 1; }
cat > hello.zig <<'EOF'
const std = @import("std");

pub fn main() !void {
    try std.io.getStdOut().writer().print("hello from zig\n", .{});
}
EOF
out=$(zig run hello.zig)
[ "$out" = "hello from zig" ] || { echo "Check failed: zig run printed '$out'"; exit 1; }
cat > hello.c <<'EOF'
#include <stdio.h>

int main(void)
{
    puts("hello from zig cc");
    return 0;
}
EOF
zig cc -o hello-c hello.c
out=$(./hello-c)
[ "$out" = "hello from zig cc" ] || { echo "Check failed: the program of zig cc printed '$out'"; exit 1; }

%install
mkdir -p %{buildroot}%{_datadir}/%{name}
echo passed > %{buildroot}%{_datadir}/%{name}/result

%files
%{_datadir}/%{name}

%changelog

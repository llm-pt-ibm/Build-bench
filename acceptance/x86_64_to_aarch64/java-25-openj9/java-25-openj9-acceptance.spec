%global debug_package %{nil}
Name:           java-25-openj9-acceptance
Version:        1
Release:        0
Summary:        Acceptance test of java-25-openj9 for Build-bench
License:        MIT
Source0:        expected-disturl
BuildRequires:  java-25-openj9-devel
BuildRequires:  java-25-openj9-headless

%description
Builds only when the java-25-openj9 under test works: java is OpenJ9 and a program hot enough for the JIT compiles and runs right.

%prep
%setup -q -c -T
cp %{SOURCE0} .

%build
# the build under test, not an older one of the distribution
disturl=$(rpm -q --qf '%%{DISTURL}\n' --whatprovides 'java-25-openj9-headless' | head -1)
grep -qxF "$disturl" expected-disturl || { echo "Check failed: java-25-openj9-headless comes from $disturl, not from the build under test"; exit 1; }
jh=$(dirname "$(dirname "$(readlink -f "$(rpm -ql java-25-openj9-devel | grep '/bin/javac$' | head -1)")")")
"$jh/bin/java" -version > version.txt 2>&1
cat version.txt
grep -qi openj9 version.txt || { echo "Check failed: java is not OpenJ9"; exit 1; }
cat > Primes.java <<'EOF'
public class Primes {
    public static void main(String[] args) {
        int count = 0;
        long sum = 0;
        for (int round = 0; round < 20; round++) {
            count = 0;
            sum = 0;
            for (int n = 2; n < 200000; n++) {
                boolean prime = true;
                for (int d = 2; (long) d * d <= n; d++) {
                    if (n % d == 0) {
                        prime = false;
                        break;
                    }
                }
                if (prime) {
                    count++;
                    sum += n;
                }
            }
        }
        System.out.println(count + " " + sum);
    }
}
EOF
"$jh/bin/javac" Primes.java
out=$("$jh/bin/java" Primes)
[ "$out" = "17984 1709600813" ] || { echo "Check failed: Primes printed '$out'"; exit 1; }

%install
mkdir -p %{buildroot}%{_datadir}/%{name}
echo passed > %{buildroot}%{_datadir}/%{name}/result

%files
%{_datadir}/%{name}

%changelog

#
# spec file for package python-torch
#
# Copyright (c) 2026 SUSE LLC and contributors
#
# All modifications and additions to the file contributed by third parties
# remain the property of their copyright owners, unless otherwise agreed
# upon. The license for this file, and modifications and additions to the
# file, is the same license as for the pristine package itself (unless the
# license for the pristine package is not an Open Source License, in which
# case the license is the MIT License). An "Open Source License" is a
# license that conforms to the Open Source Definition (Version 1.9)
# published by the Open Source Initiative.

# Please submit bugfixes or comments via https://bugs.opensuse.org/
#


%define srcname pytorch
%define pname torch
%global flavor @BUILD_FLAVOR@%{nil}
%if "%{flavor}" == "standard"
%bcond_with cuda
%endif
%if "%{flavor}" == "cuda-10-2"
%define cudaver 10-2
%bcond_without cuda
%endif
%if "%{flavor}" == "openmpi4"
%global mpi_flavor openmpi
%define mpi_ext 4
%bcond_without mpi
%bcond_without openmpi4
%endif
%if "%{flavor}" == "vulkan"
%global pkg_suffix -vulkan
%bcond_without vulkan
%endif
%if 0%{?suse_version} > 1500
%bcond_without libalternatives
%else
%bcond_with libalternatives
%endif
%bcond_with mpi
%if %{with mpi}
%global pkg_suffix %{?mpi_flavor:-%{mpi_flavor}%{?mpi_ext}}
%define pkg_prefix %{_libdir}/mpi/gcc/%{mpi_flavor}%{?mpi_ext}
%define pkg_bindir %{pkg_prefix}/bin/
%define pkg_libdir %{pkg_prefix}/%{_lib}/
%define pkg_incdir %{pkg_prefix}/include/
%define pkg_datadir %{pkg_prefix}/share/
%define pkg_sysconfdir %{pkg_prefix}%{_sysconfdir}/
%define pkg_skeldir %{pkg_prefix}%{_sysconfdir}/skel/
%define package_name   %{pname}%{?pkg_suffix}
%endif
%{?sle15_python_module_pythons}
Name:           python-torch%{?pkg_suffix}
Version:        2.14.0
Release:        0
Summary:        Deep learning framework aka pytorch/Caffe2
# Legal-Review-Notice: licences re-derived for 2.14.0 against the code that is
# actually compiled into the shipped binaries, not against third_party/ as a whole.
#  - Apache-2.0 WITH LLVM-exception: LLVM-derived sources in c10 (SmallVector.{h,cpp},
#    FunctionRef.h, llvmMathExtras.h, sparse_bitset.h) link into libc10/libtorch_cpu;
#    upstream started declaring it too in 2.13.0 (PEP 639 pyproject license expression).
#  - Zlib: aten/src/ATen/native/cpu/avx_mathfun.h (the only zlib-licensed code that is
#    built; third_party/fbgemm/external/asmjit is also zlib but USE_FBGEMM=OFF).
#  - No copyleft is linked: third_party/ittapi is BSD-3-Clause OR GPL-2.0-only and we
#    take the BSD branch; third_party/valgrind-headers carries valgrind's explicit
#    BSD-style exception for valgrind.h/callgrind.h; the only GPL text in the tree is a
#    test fixture under the unused (USE_KINETO=OFF) kineto/dynolog/cpr tree.
License:        Apache-2.0 AND Apache-2.0 WITH LLVM-exception AND BSD-2-Clause AND BSD-3-Clause AND BSL-1.0 AND MIT AND Zlib
URL:            https://pytorch.org
Source0:        pytorch-v%{version}.tar.gz
Source1:        releases.html
Source2:        python-torch-rpmlintrc
Patch1:         skip-third-party-check.patch
Patch3:         pytorch-patch-onednn.patch
Patch4:         disable-py312-intrinsics.patch
# Still not upstream in 2.13.0: XNNPACK's neonsme2 stubs fall off the end of
# non-void functions when built without XNN_ENABLE_KLEIDIAI. Not currently
# compiled here, so it is latent rather than an FTBFS - keep it anyway.
Patch5:         xnnpack-aarch64-fix.patch
BuildRequires:  %{python_module Gloo}
BuildRequires:  %{python_module PyYAML}
BuildRequires:  %{python_module devel}
BuildRequires:  %{python_module hypothesis}
BuildRequires:  %{python_module numpy-devel}
BuildRequires:  %{python_module opcodes}
BuildRequires:  %{python_module packaging}
BuildRequires:  %{python_module pip}
BuildRequires:  %{python_module protobuf}
BuildRequires:  %{python_module psutil}
BuildRequires:  %{python_module py-cpuinfo}
# 2.14.0 builds through the scikit-build-core PEP 517 backend (setup.py is
# only a deprecated shim now); %%pyproject_wheel runs with --no-build-isolation
# so the backend must come from the buildroot.
BuildRequires:  %{python_module scikit-build-core >= 1.0}
BuildRequires:  %{python_module setuptools}
BuildRequires:  %{python_module typing_extensions}
BuildRequires:  %{python_module typing}
BuildRequires:  cmake >= 3.27
BuildRequires:  fdupes
BuildRequires:  git
BuildRequires:  leveldb-devel
BuildRequires:  libnuma-devel
BuildRequires:  libopenblas_pthreads-devel
BuildRequires:  lmdb-devel
BuildRequires:  ninja
BuildRequires:  nlohmann_json-devel
BuildRequires:  openblas-devel
BuildRequires:  opencl-cpp-headers
BuildRequires:  opencl-headers
BuildRequires:  openssl-devel
BuildRequires:  pkgconfig
BuildRequires:  protobuf-c
BuildRequires:  python-rpm-macros
BuildRequires:  snappy-devel
BuildRequires:  pkgconfig(eigen3)
BuildRequires:  pkgconfig(gtest)
BuildRequires:  pkgconfig(gtest_main)
BuildRequires:  pkgconfig(libglog)
BuildRequires:  pkgconfig(libuv)
# opencv-devel only ships opencv4.pc; plain pkgconfig(opencv) is unresolvable
BuildRequires:  pkgconfig(opencv4)
BuildRequires:  pkgconfig(protobuf)
BuildRequires:  pkgconfig(protobuf-lite)
Requires:       libtorch%{?pkg_suffix} = %{version}
Requires:       python-Jinja2
Requires:       python-filelock
Requires:       python-fsspec >= 0.8.5
Requires:       python-networkx >= 2.5.1
# Not in upstream's install_requires - upstream keeps numpy optional so the PyPI
# wheel stays slim, but we build against numpy-devel (numpy support is compiled
# into torch._C) and 29 shipped modules import it at module scope. python-six
# (no importer left in 2.13.0) and python-protobuf (only torch.utils.tensorboard
# wants it, and that hard-imports tensorboard, which Factory does not have) were
# caffe2-era leftovers and are gone.
Requires:       python-numpy
Requires:       python-setuptools >= 77.0.3
Requires:       python-sympy >= 1.13.3
Requires:       python-typing_extensions >= 4.10.0
Provides:       python-caffe2%{?pkg_suffix} = %{version}
Provides:       python-pytorch%{?pkg_suffix} = %{version}
# A python call to cmake fails with a return code of 1 on this arch, disable it for now.
# and 32-bit arm is not supported
ExcludeArch:    %{ix86} %{arm}
%if %{with libalternatives}
BuildRequires:  alts
Requires:       alts
%else
Requires(post): update-alternatives
Requires(postun): update-alternatives
%endif
%ifarch x86_64
BuildRequires:  %{python_module PeachPy}
%endif
%if 0%{?suse_version} >= 1600
BuildRequires:  gcc-c++
%else
BuildRequires:  gcc12
BuildRequires:  gcc12-c++
%endif
%ifarch x86_64 aarch64 ppc64le riscv64
BuildRequires:  onednn-devel
%endif
%if %{with cuda}
BuildRequires:  cuda-compiler-%{cudaver}
BuildRequires:  cuda-cudart-dev-%{cudaver}
BuildRequires:  cuda-libraries-dev-%{cudaver}
BuildRequires:  cuda-misc-headers-%{cudaver}
BuildRequires:  cuda-nsight-%{cudaver}
BuildRequires:  cuda-toolkit-%{cudaver}
BuildRequires:  libcudnn7-devel
BuildRequires:  libnccl-devel
%endif
%if %{with openmpi4}
BuildRequires:  openmpi4-devel
Conflicts:      %{python_module torch}
%endif
%if %{with vulkan}
BuildRequires:  VulkanMemoryAllocator-devel
BuildRequires:  shaderc
BuildRequires:  pkgconfig(vulkan)
Conflicts:      %{python_module torch}
%endif
%ifarch riscv64
BuildRequires:  mold
%endif
%if "%{flavor}" == ""
ExclusiveArch:  do_not_build
%endif
%python_subpackages

%description
PyTorch enables fast, flexible experimentation and efficient production through
a hybrid front-end, distributed training, and ecosystem of tools and libraries.
The library is developed by Facebook and other groups.
PyTorch provides two high-level features:
* Tensor computing (like NumPy) with strong acceleration via graphics
* processing units (GPU) Deep neural networks built on a tape-based autodiff
  system

%package devel
Summary:        Headers for C/C++, cmake build description and libraries needed for development
Requires:       python-torch = %{version}
%if %{with openmpi4}
Conflicts:      %{python_module torch-devel}
%endif
%if %{with vulkan}
Conflicts:      %{python_module torch-devel}
%endif

%description devel
Although the Python interface is more polished and the primary focus of
development, PyTorch also has a C++ frontend. This package contains the header
to access the C/C++ interface.

%package converters
Summary:        Converters for onnx and caffe2
Requires:       python3-click
Requires:       python3-onnx
Requires:       python3-pip
Requires:       python3-pname
BuildArch:      noarch
%if %{with openmpi4}
Conflicts:      %{python_module torch-converters}
%endif
%if %{with vulkan}
Conflicts:      %{python_module torch-converters}
%endif

%description converters
Converter from caffe2 to onnx and from caffe2 to onnx formated files.

%package -n libtorch%{?pkg_suffix}
Summary:        Library which used by %{name}
%if %{with openmpi4}
Conflicts:      libtorch
%endif
%if %{with vulkan}
Conflicts:      libtorch
%endif

%description -n libtorch%{?pkg_suffix}
Library which is used by %{name}

%prep
%autosetup -p1 -n %{srcname}-v%{version}

# 64 library modules carry a vestigial python shebang (56 "#!/usr/bin/env
# python3", 4 the typo "env/python3", 4 plain "#!/usr/bin/python3") yet
# install 0644 and are only ever imported - the sole
# console script, torchrun, is generated by pip. Drop the line instead of
# rewriting the interpreter: rpmlint reports the shebang, not the interpreter.
# Here and not in %%install so that the byte-code %%pyproject_install generates
# stays valid and the %%fdupes hardlinks survive.
find torch torchgen functorch -name '*.py' -type f -print0 |
  xargs -0 -r sed -i '1{/^#!.*python/d}'

%build
cat > buildvars <<EOF
# -fno-lto must ride in CMAKE_*_FLAGS, not only CFLAGS: scikit-build-core
# forwards the CMAKE_* environment as -D cache entries, shadowing the
# CFLAGS-derived defaults, and the LTO link ICEs gcc on the SVE moments code.
export CMAKE_C_FLAGS="%{optflags} -fno-lto"
export CMAKE_CXX_FLAGS="%{optflags} -fno-lto"
export CMAKE_BUILD_TYPE="RelWithDebInfo"
export CMAKE_VERBOSE_MAKEFILE=ON
# The tar_scm tarball has no .git and version.txt reads "2.14.0a0", so without
# these the wheel metadata (and torch.__version__) would say 2.14.0a0. Same
# variables upstream's own release pipeline sets; build 1 has no .post suffix.
export PYTORCH_BUILD_VERSION="%{version}"
export PYTORCH_BUILD_NUMBER=1
# Build system configuration
export BLAS=OpenBLAS
export MAX_JOBS=%{?jobs}
%if 0%{?suse_version} >= 1600
export CC=gcc-%{gcc_version}
export CXX=g++-%{gcc_version}
%else
export CC=gcc-12
export CXX=g++-12
%endif

# Core PyTorch options
export USE_OPENMP=ON
export USE_DISTRIBUTED=ON
export BUILD_CUSTOM_PROTOBUF=OFF
export BUILD_TEST=OFF
export USE_SYSTEM_BENCHMARK=ON
export USE_SYSTEM_EIGEN_INSTALL=ON

# Hardware acceleration
%if %{with cuda}
# Literal paths on purpose: /usr/local/cuda-* is the CUDA installer's own
# layout, not a path we own, and %%{_prefix}/local is not the same statement.
# spec-cleaner rewrites these - accepted deviation.
export USE_SYSTEM_NCCL=ON
export NCCL_INCLUDE_DIR="/usr/include/"
export USE_CUDA=ON
export USE_CUDNN=ON
export PATH="/usr/local/cuda-10.1/bin:$PATH"
export CPLUS_INCLUDE_PATH="/usr/local/cuda-10.1/include"
export C_INCLUDE_PATH="/usr/local/cuda-10.1/include"
export LD_LIBRARY_PATH="/usr/local/cuda-10.1/lib"
%else
export USE_CUDA=OFF
export USE_CUDNN=OFF
%endif

%if 0%{?sle_version} == 150600
export USE_MKLDNN=OFF
export USE_OPENCL=OFF
%else
export USE_MKLDNN=ON
%endif

%if %{with vulkan}
export USE_VULKAN=ON
%endif

# MPI configuration
%if %{with mpi}
export USE_MPI=ON
export MPIEXEC_EXECUTABLE="%{pkg_bindir}/mpiexec"
export USE_GLOO=OFF
%else
export USE_MPI=OFF
export USE_GLOO=ON
%endif

# Disable optional features
export USE_KINETO=OFF
export USE_FBGEMM=OFF
export USE_NNPACK=OFF
export USE_NCCL=OFF

# Compiler flags - start with RPM's standard cmake flags, then add PyTorch-specific needs
# Disable LTO to avoid GCC internal compiler errors on complex template code
export CFLAGS="\${CMAKE_C_FLAGS} -fno-lto"
export CXXFLAGS="\${CMAKE_CXX_FLAGS} -fno-lto"
%if %{with vulkan}
export CXXFLAGS="\${CXXFLAGS} -I %{_prefix}/ -Wno-error=return-type"
%endif
%ifarch aarch64
export CFLAGS="\${CFLAGS} -Wno-incompatible-pointer-types"
%endif
export LDFLAGS="\${LDFLAGS} -Wl,--allow-shlib-undefined"
%ifarch riscv64
LDFLAGS+=" -fuse-ld=mold"
%endif
EOF

# Build both C++ libraries and Python bindings in a single pass
source ./buildvars
export BUILD_PYTHON=ON
%pyproject_wheel

%install
source ./buildvars
export BUILD_PYTHON=ON
%pyproject_install

# 2.13.0 started vendoring third_party license texts into dist-info/licenses;
# two arrive mode 0755 and miniz's has CRLF, which rpmlint reads as a script.
# Must precede %%fdupes: sed -i replaces the inode, so doing this afterwards
# breaks the hardlinks and reintroduces the duplicate waste fdupes removed.
find %{buildroot} -path '*.dist-info/licenses/*' -type f -exec chmod 0644 {} +
find %{buildroot} -path '*.dist-info/licenses/*' -type f -exec sed -i 's|\r$||' {} +

%python_expand %fdupes %{buildroot}%{$python_sitearch}

# Move libtorch libraries to %%{_libdir} for the separate libtorch package
# Only move core libtorch libraries, not all .so files
%python_expand mkdir -p %{buildroot}%{_libdir}
%python_expand cp -P %{buildroot}%{$python_sitearch}/torch/lib/libtorch.so* %{buildroot}%{_libdir}/ 2>/dev/null || true
%python_expand cp -P %{buildroot}%{$python_sitearch}/torch/lib/libtorch_cpu.so* %{buildroot}%{_libdir}/ 2>/dev/null || true
%python_expand cp -P %{buildroot}%{$python_sitearch}/torch/lib/libc10.so* %{buildroot}%{_libdir}/ 2>/dev/null || true
# Remove the originals from sitearch
%python_expand rm -f %{buildroot}%{$python_sitearch}/torch/lib/libtorch.so*
%python_expand rm -f %{buildroot}%{$python_sitearch}/torch/lib/libtorch_cpu.so*
%python_expand rm -f %{buildroot}%{$python_sitearch}/torch/lib/libc10.so*
# The shipped CMake package config (Caffe2Targets*.cmake, TorchConfig.cmake)
# references these libraries relative to the torch/ install prefix
# (${_IMPORT_PREFIX}/lib/lib*.so and find_library(... PATHS ${TORCH_INSTALL_PREFIX}/lib)).
# Recreate them as symlinks to the moved libraries in %%{_libdir} so that
# find_package(Torch) resolves for downstream C++ consumers.
%python_expand ln -sf %{_libdir}/libtorch.so %{buildroot}%{$python_sitearch}/torch/lib/libtorch.so
%python_expand ln -sf %{_libdir}/libtorch_cpu.so %{buildroot}%{$python_sitearch}/torch/lib/libtorch_cpu.so
%python_expand ln -sf %{_libdir}/libc10.so %{buildroot}%{$python_sitearch}/torch/lib/libc10.so

%python_clone -a %{buildroot}%{_bindir}/torchrun
# 2.14.0 adds a second console script, the Flight Recorder tracer.
%python_clone -a %{buildroot}%{_bindir}/torchfrtrace

# Move header files from main package to devel package locations
%python_expand mkdir -p %{buildroot}%{$python_sitearch}/torch-devel/csrc/inductor/aoti_runtime
%python_expand mkdir -p %{buildroot}%{$python_sitearch}/torch-devel/lib/libshm
%python_expand mkdir -p %{buildroot}%{$python_sitearch}/torch-devel/lib/libshm_windows
%python_expand mv %{buildroot}%{$python_sitearch}/torch/csrc/inductor/aoti_runtime/model.h %{buildroot}%{$python_sitearch}/torch-devel/csrc/inductor/aoti_runtime/
%python_expand mv %{buildroot}%{$python_sitearch}/torch/lib/libshm/*.h %{buildroot}%{$python_sitearch}/torch-devel/lib/libshm/
%python_expand rm -rf %{buildroot}%{$python_sitearch}/torch/lib/libshm_windows

%pre
%python_libalternatives_reset_alternative torchrun
%python_libalternatives_reset_alternative torchfrtrace

%post
%python_install_alternative torchrun
%python_install_alternative torchfrtrace

%postun
%python_uninstall_alternative torchrun
%python_uninstall_alternative torchfrtrace

%post -n libtorch%{?pkg_suffix} -p /sbin/ldconfig
%postun -n libtorch%{?pkg_suffix} -p /sbin/ldconfig

%files %{python_files}
%doc README.md NOTICE
%license LICENSE
%{python_sitearch}/torch*
%{python_sitearch}/torchgen/
%{python_sitearch}/functorch/
%exclude %{python_sitearch}/torch/share
%exclude %{python_sitearch}/torch/include
%exclude %{python_sitearch}/torch/_inductor/codegen
%exclude %{python_sitearch}/torch/utils/benchmark/utils/
%exclude %{python_sitearch}/torchgen/packaged/ATen/templates
%exclude %{python_sitearch}/torchgen/packaged/autograd/templates
%exclude %{python_sitearch}/torch-devel
# The real libtorch libraries live in the separate libtorch package; the main
# package ships only compatibility symlinks under torch/lib pointing at
# %%{_libdir} so the shipped CMake config resolves for downstream consumers.
%python_alternative %{_bindir}/torchrun
%python_alternative %{_bindir}/torchfrtrace

%files %{python_files devel}
%{python_sitearch}/torch/share
%{python_sitearch}/torch/include
%{python_sitearch}/torch/_inductor/codegen
%{python_sitearch}/torch/utils/benchmark/utils/
%{python_sitearch}/torchgen/packaged/ATen/templates
%{python_sitearch}/torchgen/packaged/autograd/templates
%{python_sitearch}/torch-devel/

%files -n libtorch%{?pkg_suffix}
%{_libdir}/libtorch.so*
%{_libdir}/libtorch_cpu.so*
%{_libdir}/libc10.so*

%changelog

# Historical PROJ native component profile

This opt-in Linux amd64 recipe builds the official ATAK-pinned **PROJ 4.9.1**
source unchanged as a static PIC library. It is separate from server packaging,
default tasks and the Assimp/LAS profiles. It does not update production PROJ.

The immutable source is `takthirdparty/distfiles/proj.tar.gz` at official
[ATAK revision 9f6893dd657feacc35ec5de03dad721c2e44170e](https://github.com/TAK-Product-Center/atak-civ/tree/9f6893dd657feacc35ec5de03dad721c2e44170e).
The lock fixes archive size/hash, exact bounded extraction inventory, COPYING
path/hash and tool versions. The vendor JNI-header patch is not applied: this
profile configures `--without-jni` and consumes untouched source.

Provide GCC 14.2.0, GNU Make 4.4.1, CMake 3.31.6 and GNU binutils 2.44 separately.
The entrypoint records executable paths, versions and SHA256 before execution
and verifies hashes afterward. Tool installation/authentication is separate.
The default uses only an already verified cache entry named by archive SHA256:

```sh
python3 takx/native-proj/build.py --output /absolute/new-proj-proof \
  --cache /absolute/proj-cache --cmake /absolute/cmake
```

`--fetch-dependencies` explicitly permits fetching the exact locked public
archive; offline operation never falls back to the network or host PROJ.
Output must be new, external to the checkout, and separate from cache. Use a
dedicated cache: their combined retained files are bounded to 256 MiB. Builds
use one make job, a 600-second build step and a 900-second shared command
deadline. Commands own process groups and cap complete output via the existing
native helper; this does not impose a filesystem file-size limit.

The genuine C consumer links the explicit installed `libproj.a` and asserts
`PJ_VERSION == 491`, the actual release string, known spherical-Mercator
coordinates for longitude 0/+10/-10 and latitude 0/+45/-45 degrees, preserved
height, and inverse geographic radians. A separate whole-archive shared link
uses `--no-undefined` and rejects TEXTREL. Runtime closure rejects host shared
PROJ. Source inventory, archive, license, installed files, consumer source,
recipe and tools are checked after the controls; `complete.json` is written
only after success. A previous standalone proof is background evidence, never
adopted as this entrypoint's result.

```sh
python3 -m unittest discover -s takx/native-proj -p test_build.py -v
TAKX_NATIVE_PROJ_PROOF=/absolute/new-proj-proof \
  python3 -m unittest discover -s takx/native-proj -p test_build.py -v
```

This validates ordinary historical coordinate/PIC component behavior on the
host ABI only. No JNI, modern PROJ API/ABI compatibility, security assessment,
fault/parser experiments, full upstream suite, target-image ABI, complete TTP,
Kernel SDK or TAKX client/runtime acceptance is claimed.

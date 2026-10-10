# History: building MD.emu 1.4.17D on an iPad 2 (iOS 6.1.3, jailbroken)

Historical record of how the author built MD.emu directly on the target device, recovered from the author's build log. It is not part of Retro Selector, not a supported procedure and not a guarantee for other devices, SDKs or package versions. Cydia/APT packages may no longer be available. No SDK, ROMs, BIOS or credentials are included or distributed here.

## Status

Confirmed by the author: the app opens its menu and lets you browse folders in `Load Game`. Not yet tested: ROMs, performance, sound and iCade (the build includes iCade support, but it has not been verified). Sega CD was already disabled (`NO_SCD` in `build.mk`). Keep `roms_md/` as Retro Selector's local source.

## Tools (Cydia/APT)

| Package | Recorded version |
| --- | --- |
| `org.coolstar.llvm-clang32` | package 3.7.1-2 (`clang` and `clang++` reported 3.7.1) |
| `org.coolstar.ld64` | package candidate 274.2 (`ld -v` reported 253.3; both values are kept deliberately) |
| `org.coolstar.cctools` | 895 |
| `make` | 3.81-2p (GNU Make 3.81) |
| `uuid` | 1.6.0-2p (dependency selected by APT) |
| `pkg-config` | 0.23-1p (installed separately) |
| `ldid` | 1:1.2.1 (already installed) |

Bash and `uicache` were also available; versions of unrecorded packages are not inferred.

```bash
apt-get -s install org.coolstar.llvm-clang32 org.coolstar.ld64 org.coolstar.cctools make
apt-get install org.coolstar.llvm-clang32 org.coolstar.ld64 org.coolstar.cctools make
apt-get install pkg-config
```

The simulation added five packages, including `uuid`, with no removals or upgrades. `pkg-config` is a basic step installed separately.

## Source and SDK

- Source: a copy of `neonichu/MD.emu` at `/var/root/MD.emu-master`. The Imagine engine declares 1.4.17; 1.4.17D is the version the author gives to their own build.
- SDK: `iPhoneOS5.0.sdk`, extracted separately from Xcode material (not installed by Cydia) at `/var/root/sdk-extract-mdemu/Platforms/iPhoneOS.platform/Developer/SDKs/iPhoneOS5.0.sdk`. Do not distribute it.
- The ARMv7 libraries for BTstack, FreeType, libpng15 and the ZIP objects were already in `imagine/bundle/darwin-iOS/armv7`; they did not come from Cydia.

## Required patch

In `imagine/src/fs/posix/FsPosix.cc`, back up the file first, then replace the unconditional `SELECTOR_CONST` definition with:

```cpp
#if defined(CONFIG_BASE_IOS)
#define SELECTOR_CONST
#else
#define SELECTOR_CONST const
#endif
```

This adapts the `scandir` filters to the SDK used. Do not modify the SDK headers; it is not a universal patch.

## Build command

Reconstructed from the successful log (some lines in the source PDF were cut off):

```bash
cd /var/root/MD.emu-master/MD.emu
SDK=/var/root/sdk-extract-mdemu/Platforms/iPhoneOS.platform/Developer/SDKs/iPhoneOS5.0.sdk
ARMV7=/var/root/MD.emu-master/imagine/bundle/darwin-iOS/armv7
make -j1 -f ios-armv7.mk \
  IMAGINE_PATH=/var/root/MD.emu-master/imagine \
  package_freetype_externalPath="$ARMV7" \
  IOS_SYSROOT="$SDK" \
  CC='clang -Wno-gnu-array-member-paren-init -Wno-reserved-user-defined-literal -Wno-error=c++11-narrowing' \
  CXX='clang++ -Wno-gnu-array-member-paren-init -Wno-reserved-user-defined-literal -Wno-error=c++11-narrowing' \
  > /var/root/mdemu-build.log 2>&1
BUILD_STATUS=$?
printf 'Build exit status: %s\n' "$BUILD_STATUS"
tail -n 60 /var/root/mdemu-build.log
```

- Do not use `package_libpng_externalPath`: its branch asks for png14, while the bundle contains png15.
- `ios-armv7.mk` produces a debug binary without the release/LTO configuration; it is not an optimized release build.

## Result and checks

Exit status 0; linked and signed with `ldid -S`; binary `target/iOS/bin-debug/mdemu-armv7`. `otool -hv` and `lipo -info` confirmed ARMv7.

```bash
BIN=target/iOS/bin-debug/mdemu-armv7
otool -hv "$BIN"
lipo -info "$BIN"
otool -L "$BIN"
```

There were warnings, including `shift count >= width of type`: a successful build does not guarantee the absence of problems.

## Local installation

The bundle was prepared in `/var/root/mdemu-stage/MdEmu.app` and copied to `/Applications/MdEmu.app`: owner `root:wheel`, directory and the `mdemu`/`mdemu_` executables 755, resources 644, no setuid. Copying only the binary is not enough: the bundle's `Info.plist`, font, images and icons are required. The `mdemu_` launcher:

```bash
#!/bin/bash
dir=$(dirname "$0")
exec "${dir}/mdemu" "$@"
```

Registered with `su mobile -c /usr/bin/uicache`. Do not run the project's `*-install` targets: they point to `iphone4s` over SSH and apply setuid.

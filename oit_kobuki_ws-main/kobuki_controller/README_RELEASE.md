# Kobuki Controller v1.0 Release

## Build prerequisites
- Java 17
- Android SDK / NDK accepted
- Flutter SDK

## Recommended release signing
1. Create a keystore.
2. Copy `android/key.properties.example` to `android/key.properties`.
3. Fill in the keystore path and passwords.

Example keystore command:

```bash
keytool -genkeypair   -v   -keystore ~/kobuki-controller.jks   -alias kobuki_controller   -keyalg RSA   -keysize 2048   -validity 10000
```

## Build APK
```bash
cd kobuki_controller
flutter build apk --release   --dart-define=KOBUKI_WIFI_HOST=192.168.179.9   --dart-define=KOBUKI_CMD_VEL_TOPIC=/commands/velocity
```

Output APK:
- `build/app/outputs/flutter-apk/app-release.apk`

## Build App Bundle
```bash
cd kobuki_controller
flutter build appbundle --release   --dart-define=KOBUKI_WIFI_HOST=192.168.179.9   --dart-define=KOBUKI_CMD_VEL_TOPIC=/commands/velocity
```

Output AAB:
- `build/app/outputs/bundle/release/app-release.aab`

## Use the built APK on Android
1. Build the release APK.
2. Find the output file at `build/app/outputs/flutter-apk/app-release.apk`.
3. Transfer the APK to the Android phone. Typical methods:
   - USB file transfer
   - Google Drive / Dropbox / Nextcloud
   - Email or chat attachment
4. On the phone, open the APK file.
5. If Android blocks the install, allow installs from that app once when prompted.
   - For example, allow installs from Files, Chrome, Drive, or the app used to open the APK.
6. Complete the installation.
7. After installation, launch `Kobuki Controller` from the home screen. USB is not required for normal use.

Notes:
- If you install a newer APK signed with the same key, Android updates the existing app in place.
- If the signing key changes, Android treats it as a different app and in-place update will fail.

## Install on a device without USB debug session
```bash
adb install -r build/app/outputs/flutter-apk/app-release.apk
```

After installation, the app launches standalone from the launcher. USB is not required for normal use.

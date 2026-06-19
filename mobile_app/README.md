# mobile_app

Offline Android companion app for Local-Video-Renamer.

## Local Gradle Workflow

This project is configured to prefer an already installed local Gradle distribution before falling back to the wrapper download step.

Priority order:

1. `LOCAL_GRADLE_HOME`
2. `%USERPROFILE%\.gradle\wrapper\dists\gradle-9.4.1-bin\...\gradle-9.4.1`
3. default Gradle wrapper download behavior

This helps on machines where `flutter run` fails because Gradle cannot download artifacts from the network.

### Windows example

```powershell
$env:LOCAL_GRADLE_HOME = 'C:\Users\WWT\.gradle\wrapper\dists\gradle-9.4.1-bin\45w7kj7s8jzqenl33wrwa0aoj\gradle-9.4.1'
flutter run -d <device-id>
```

If `LOCAL_GRADLE_HOME` is not set, `android\gradlew.bat` will automatically scan the local Gradle cache for `gradle-9.4.1`.

## Common Commands

```powershell
flutter devices
flutter run -d <device-id>
flutter build apk --debug
```

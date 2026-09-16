# Add project specific ProGuard rules here.
# You can control the set of applied configuration files using the
# proguardFiles setting in build.gradle.

# Keep Javascript interfaces so they are not obfuscated and can be called from webview
-keepclassmembers class * {
    @android.webkit.JavascriptInterface <methods>;
}
-keepattributes JavascriptInterface
-keep public class com.dtech.uni.MainActivity$WebAppInterface
-keep public class * implements com.dtech.uni.MainActivity$WebAppInterface
-keepclassmembers class com.dtech.uni.MainActivity$WebAppInterface {
    <methods>;
}

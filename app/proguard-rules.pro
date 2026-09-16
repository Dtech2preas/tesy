# Add project specific ProGuard rules here.
# You can control the set of applied configuration files using the
# proguardFiles setting in build.gradle.

# Keep Javascript interfaces so they are not obfuscated and can be called from webview
-keepclassmembers class * {
    @android.webkit.JavascriptInterface <methods>;
}
-keepattributes JavascriptInterface
-keep public class com.dtechx24.uni.MainActivity$WebAppInterface
-keep public class * implements com.dtechx24.uni.MainActivity$WebAppInterface
-keepclassmembers class com.dtechx24.uni.MainActivity$WebAppInterface {
    <methods>;
}

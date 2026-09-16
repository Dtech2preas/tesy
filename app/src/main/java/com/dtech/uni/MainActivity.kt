package com.dtech.uni

import android.annotation.SuppressLint
import android.content.Intent
import android.net.Uri
import android.os.Bundle
import android.webkit.WebResourceRequest
import android.webkit.WebSettings
import android.webkit.WebView
import android.webkit.WebViewClient
import androidx.appcompat.app.AppCompatActivity
import androidx.core.splashscreen.SplashScreen.Companion.installSplashScreen
import androidx.swiperefreshlayout.widget.SwipeRefreshLayout
import android.content.Context
import android.net.ConnectivityManager
import android.net.NetworkCapabilities
import android.webkit.JavascriptInterface
import android.webkit.WebChromeClient
import android.os.Message
import android.webkit.DownloadListener
import android.os.Environment
import android.util.Base64
import java.io.File
import java.io.FileOutputStream
import android.widget.Toast
import android.media.MediaScannerConnection
import android.content.pm.PackageManager
import android.os.Build
import androidx.core.app.ActivityCompat
import androidx.core.content.ContextCompat
import android.Manifest
import android.webkit.WebResourceResponse
import androidx.webkit.WebViewAssetLoader
import androidx.webkit.WebViewClientCompat
import android.view.View
import android.view.animation.AnimationUtils
import android.widget.ImageView

class MainActivity : AppCompatActivity() {

    private lateinit var webView: WebView
    private lateinit var swipeRefreshLayout: SwipeRefreshLayout

    @SuppressLint("SetJavaScriptEnabled")
    override fun onCreate(savedInstanceState: Bundle?) {
        val splashScreen = installSplashScreen()
        super.onCreate(savedInstanceState)
        setContentView(R.layout.activity_main)

        swipeRefreshLayout = findViewById(R.id.swipe_refresh)
        webView = findViewById(R.id.webview)

        // Setup custom splash animation
        val splashScreenLayout = findViewById<View>(R.id.splash_screen_layout)
        val waveBackground = findViewById<ImageView>(R.id.wave_background)
        val waveAnimation = AnimationUtils.loadAnimation(this, R.anim.wave_animation)
        waveBackground.startAnimation(waveAnimation)
        val webSettings: WebSettings = webView.settings

        // Enable JavaScript
        webSettings.javaScriptEnabled = true

        // Enable DOM Storage (crucial for local storage and modern web apps)
        webSettings.domStorageEnabled = true

        // Allow mix content (http inside https)
        webSettings.mixedContentMode = WebSettings.MIXED_CONTENT_ALWAYS_ALLOW

        // Allow file access for local assets
        webSettings.allowFileAccess = true
        webSettings.allowFileAccessFromFileURLs = true
        webSettings.allowUniversalAccessFromFileURLs = true

        // Other useful settings
        webSettings.loadWithOverviewMode = true
        webSettings.useWideViewPort = true
        webSettings.builtInZoomControls = true
        webSettings.displayZoomControls = false

        // Enable multiple windows for window.open
        webSettings.setSupportMultipleWindows(true)
        webSettings.javaScriptCanOpenWindowsAutomatically = true

        // Configure Asset Loader to bypass CORS issues for fetch() and modules
        val assetLoader = WebViewAssetLoader.Builder()
            .addPathHandler("/assets/", WebViewAssetLoader.AssetsPathHandler(this))
            .build()

        webView.webViewClient = object : WebViewClientCompat() {
            override fun shouldInterceptRequest(
                view: WebView,
                request: WebResourceRequest
            ): WebResourceResponse? {
                return assetLoader.shouldInterceptRequest(request.url)
            }

            override fun onPageFinished(view: WebView, url: String) {
                super.onPageFinished(view, url)
                swipeRefreshLayout.isRefreshing = false

                // Hide custom splash screen once webview is ready, but keep it for at least 2 seconds
                if (splashScreenLayout.visibility == View.VISIBLE) {
                    splashScreenLayout.postDelayed({
                        splashScreenLayout.animate()
                            .alpha(0f)
                            .setDuration(500)
                            .withEndAction {
                                splashScreenLayout.visibility = View.GONE
                            }
                            .start()
                    }, 2000)
                }
            }

            override fun shouldOverrideUrlLoading(view: WebView, request: WebResourceRequest): Boolean {
                val url = request.url.toString()
                return handleUrl(url, view)
            }

            @Suppress("DEPRECATION")
            override fun shouldOverrideUrlLoading(view: WebView, url: String): Boolean {
                return handleUrl(url, view)
            }

            private fun handleUrl(url: String, view: WebView): Boolean {
                // Allow standard https and the special appassets domain
                if (url.startsWith("http://") || url.startsWith("https://")) {
                    return false
                }

                // Handle intent schemes, market links, shein://, etc.
                try {
                    val intent: Intent = if (url.startsWith("intent://")) {
                        Intent.parseUri(url, Intent.URI_INTENT_SCHEME)
                    } else {
                        Intent(Intent.ACTION_VIEW, Uri.parse(url))
                    }

                    // Add flags to open outside our app properly
                    intent.addFlags(Intent.FLAG_ACTIVITY_NEW_TASK)

                    // Try to start the activity
                    if (intent.resolveActivity(packageManager) != null) {
                        startActivity(intent)
                        return true
                    }

                    // If it was an intent scheme and we couldn't resolve it, try the fallback URL
                    if (url.startsWith("intent://")) {
                        val fallbackUrl = intent.getStringExtra("browser_fallback_url")
                        if (fallbackUrl != null) {
                            view.loadUrl(fallbackUrl)
                            return true
                        }
                    }
                } catch (e: Exception) {
                    e.printStackTrace()
                }

                return true // We handled it (or tried to)
            }
        }

        // WebChromeClient to handle window.open() to an external browser
        webView.webChromeClient = object : WebChromeClient() {
            override fun onCreateWindow(view: WebView?, isDialog: Boolean, isUserGesture: Boolean, resultMsg: Message?): Boolean {
                val transport = resultMsg?.obj as WebView.WebViewTransport
                val newWebView = WebView(this@MainActivity)
                newWebView.webViewClient = object : WebViewClient() {
                    override fun shouldOverrideUrlLoading(view: WebView?, request: WebResourceRequest?): Boolean {
                        val url = request?.url.toString()
                        try {
                            val intent = Intent(Intent.ACTION_VIEW, Uri.parse(url))
                            intent.addFlags(Intent.FLAG_ACTIVITY_NEW_TASK)
                            if (intent.resolveActivity(packageManager) != null) {
                                startActivity(intent)
                            } else {
                                Toast.makeText(this@MainActivity, "No app can handle this action", Toast.LENGTH_SHORT).show()
                            }
                        } catch (e: Exception) {
                            e.printStackTrace()
                        }
                        return true
                    }
                }
                transport.webView = newWebView
                resultMsg.sendToTarget()
                return true
            }
        }

        // Setup pull-to-refresh
        swipeRefreshLayout.setOnRefreshListener {
            webView.reload()
        }

        // Add JS Interface for checking network status securely and saving files
        webView.addJavascriptInterface(WebAppInterface(this), "AndroidApp")

        // Load the target URL via the local asset domain to prevent CORS/Fetch issues
        webView.loadUrl("https://appassets.androidplatform.net/assets/www/index.html")
    }

    private fun isAppUrl(url: String): Boolean {
        // Only allow interface access if it's our local asset domain or live domain
        return url.startsWith("https://appassets.androidplatform.net") || url.contains("uni.dtech-services.co.za")
    }

    override fun onBackPressed() {
        if (webView.canGoBack()) {
            webView.goBack()
        } else {
            super.onBackPressed()
        }
    }

    override fun onRequestPermissionsResult(requestCode: Int, permissions: Array<out String>, grantResults: IntArray) {
        super.onRequestPermissionsResult(requestCode, permissions, grantResults)
        if (requestCode == 100) {
            if (grantResults.isNotEmpty() && grantResults[0] == PackageManager.PERMISSION_GRANTED) {
                // For now, we assume the user will just click download again if it fails here
                Toast.makeText(this, "Permission granted, please click download again.", Toast.LENGTH_SHORT).show()
            } else {
                Toast.makeText(this, "Permission denied to save PDF.", Toast.LENGTH_SHORT).show()
            }
        }
    }

    // WebAppInterface allows javascript to communicate with Kotlin natively
    inner class WebAppInterface(private val mContext: Context) {
        @JavascriptInterface
        fun isOnline(): Boolean {
            if (!isAppUrl(webView.url ?: "")) return false
            val connectivityManager = mContext.getSystemService(Context.CONNECTIVITY_SERVICE) as ConnectivityManager
            val network = connectivityManager.activeNetwork ?: return false
            val activeNetwork = connectivityManager.getNetworkCapabilities(network) ?: return false
            return when {
                activeNetwork.hasTransport(NetworkCapabilities.TRANSPORT_WIFI) -> true
                activeNetwork.hasTransport(NetworkCapabilities.TRANSPORT_CELLULAR) -> true
                activeNetwork.hasTransport(NetworkCapabilities.TRANSPORT_ETHERNET) -> true
                else -> false
            }
        }


        @JavascriptInterface
        fun saveBase64Pdf(base64String: String, filename: String) {
            if (!isAppUrl(webView.url ?: "")) return

            // Request runtime permissions on older Android versions
            if (Build.VERSION.SDK_INT <= Build.VERSION_CODES.P &&
                ContextCompat.checkSelfPermission(mContext, Manifest.permission.WRITE_EXTERNAL_STORAGE) != PackageManager.PERMISSION_GRANTED) {
                ActivityCompat.requestPermissions(
                    mContext as AppCompatActivity,
                    arrayOf(Manifest.permission.WRITE_EXTERNAL_STORAGE),
                    100
                )
                return
            }

            executeSaveBase64Pdf(base64String, filename)
        }

        fun executeSaveBase64Pdf(base64String: String, filename: String) {
            try {
                // Ensure filename is safe (no path traversal)
                val safeFilename = filename.replace(Regex("[^a-zA-Z0-9._-]"), "_")
                if (safeFilename.isEmpty() || safeFilename.contains("..")) {
                    throw IllegalArgumentException("Invalid filename")
                }
                val downloadsDir = Environment.getExternalStoragePublicDirectory(Environment.DIRECTORY_DOWNLOADS)
                val file = File(downloadsDir, safeFilename)
                val pdfAsBytes = Base64.decode(base64String.replaceFirst("^data:application/pdf;base64,".toRegex(), ""), 0)
                val os = FileOutputStream(file, false)
                os.write(pdfAsBytes)
                os.flush()
                os.close()

                // Notify media scanner
                MediaScannerConnection.scanFile(mContext, arrayOf(file.absolutePath), null, null)

                (mContext as AppCompatActivity).runOnUiThread {
                    Toast.makeText(mContext, "PDF Saved to Downloads", Toast.LENGTH_LONG).show()
                }
            } catch (e: Exception) {
                e.printStackTrace()
                (mContext as AppCompatActivity).runOnUiThread {
                    Toast.makeText(mContext, "Failed to save PDF: ${e.message}", Toast.LENGTH_LONG).show()
                }
            }
        }
    }
}

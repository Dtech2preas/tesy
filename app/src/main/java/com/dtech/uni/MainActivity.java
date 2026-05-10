package com.dtech.uni;

import android.annotation.SuppressLint;
import android.content.Intent;
import android.net.Uri;
import android.os.Bundle;
import android.webkit.WebResourceRequest;
import android.webkit.WebSettings;
import android.webkit.WebView;
import android.webkit.WebViewClient;
import androidx.appcompat.app.AppCompatActivity;

public class MainActivity extends AppCompatActivity {

    private WebView webView;

    @SuppressLint("SetJavaScriptEnabled")
    @Override
    protected void onCreate(Bundle savedInstanceState) {
        super.onCreate(savedInstanceState);
        setContentView(R.layout.activity_main);

        webView = findViewById(R.id.webview);
        WebSettings webSettings = webView.getSettings();

        // Enable JavaScript
        webSettings.setJavaScriptEnabled(true);

        // Enable DOM Storage (crucial for local storage and modern web apps)
        webSettings.setDomStorageEnabled(true);

        // Allow mix content (http inside https)
        webSettings.setMixedContentMode(WebSettings.MIXED_CONTENT_ALWAYS_ALLOW);

        // Other useful settings
        webSettings.setLoadWithOverviewMode(true);
        webSettings.setUseWideViewPort(true);
        webSettings.setBuiltInZoomControls(true);
        webSettings.setDisplayZoomControls(false);

        webView.setWebViewClient(new WebViewClient() {
            @Override
            public boolean shouldOverrideUrlLoading(WebView view, WebResourceRequest request) {
                String url = request.getUrl().toString();
                return handleUrl(url, view);
            }

            @SuppressWarnings("deprecation")
            @Override
            public boolean shouldOverrideUrlLoading(WebView view, String url) {
                return handleUrl(url, view);
            }

            private boolean handleUrl(String url, WebView view) {
                if (url.startsWith("http://") || url.startsWith("https://")) {
                    // Load standard web URLs in the WebView
                    return false;
                }

                // Handle intent schemes, market links, shein://, etc.
                try {
                    Intent intent;
                    if (url.startsWith("intent://")) {
                        intent = Intent.parseUri(url, Intent.URI_INTENT_SCHEME);
                    } else {
                        intent = new Intent(Intent.ACTION_VIEW, Uri.parse(url));
                    }

                    // Add flags to open outside our app properly
                    intent.addFlags(Intent.FLAG_ACTIVITY_NEW_TASK);

                    // Try to start the activity
                    if (intent.resolveActivity(getPackageManager()) != null) {
                        startActivity(intent);
                        return true;
                    }

                    // If it was an intent scheme and we couldn't resolve it, try the fallback URL
                    if (url.startsWith("intent://")) {
                        String fallbackUrl = intent.getStringExtra("browser_fallback_url");
                        if (fallbackUrl != null) {
                            view.loadUrl(fallbackUrl);
                            return true;
                        }
                    }
                } catch (Exception e) {
                    e.printStackTrace();
                }

                return true; // We handled it (or tried to)
            }
        });

        // Load the target URL
        webView.loadUrl("https://uni.dtech-services.co.za");
    }

    @Override
    public void onBackPressed() {
        if (webView.canGoBack()) {
            webView.goBack();
        } else {
            super.onBackPressed();
        }
    }
}

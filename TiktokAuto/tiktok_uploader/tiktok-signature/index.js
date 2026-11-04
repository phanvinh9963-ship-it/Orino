const { createCipheriv } = require("crypto");
const { devices, chromium } = require("playwright-chromium");
const Utils = require("./utils");

const iPhone11 = devices["iPhone 11 Pro"];

class Signer {
    constructor(default_url, userAgent, browser) {
        this.userAgent =
            userAgent ||
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36";

        this.default_url =
            default_url || "https://www.tiktok.com/";

        this.password = "webapp1.0+202106";

        this.args = [
            "--disable-blink-features=AutomationControlled",
            "--disable-infobars",
            "--window-size=1920,1080",
            "--start-maximized"
        ];

        this.args.push(`--user-agent=${this.userAgent}`);

        this.browser = browser || null;
        this.isExternalBrowser = !!browser;
        this.context = null;
        this.page = null;

        this.options = {
            headless: true,
            args: this.args,
            ignoreDefaultArgs: [
                "--mute-audio",
                "--hide-scrollbars"
            ],
            ignoreHTTPSErrors: true
        };
    }

    async init() {
        console.log("[SIGN] Starting browser...");

        if (!this.browser) {
            this.browser = await chromium.launch(
                this.options
            );
        }

        const emulateTemplate = {
            ...iPhone11,
            locale: "en-US",
            deviceScaleFactor: 1,
            isMobile: false,
            hasTouch: false,
            userAgent: this.userAgent,
            viewport: {
                width: 1920,
                height: 1080
            }
        };

        this.context = await this.browser.newContext({
            bypassCSP: true,
            ...emulateTemplate
        });

        this.page = await this.context.newPage();

        console.log("[SIGN] Opening TikTok...");

        await this.page.goto(
            this.default_url,
            {
                waitUntil: "domcontentloaded",
                timeout: 60000
            }
        );

        await this.page.waitForTimeout(5000);

        console.log("[SIGN] Loading local signer scripts...");

        const scripts = [
            "signer.js",
            "webmssdk.js",
            "xbogus.js"
        ];

        for (const script of scripts) {
            const scriptPath =
                `${__dirname}/javascript/${script}`;

            try {
                await this.page.addScriptTag({
                    path: scriptPath
                });

                console.log(
                    `[SIGN] Loaded ${script}`
                );
            } catch (err) {
                console.error(
                    `[SIGN] Failed loading ${script}`
                );
                throw err;
            }
        }

        await this.page.waitForTimeout(2000);

        const status = await this.page.evaluate(() => {
            return {
                byted_acrawler:
                    typeof window.byted_acrawler,

                sign:
                    typeof window.byted_acrawler?.sign,

                generateBogus:
                    typeof window.generateBogus
            };
        });

        console.log(
            "[SIGN] Environment:",
            JSON.stringify(status)
        );

        if (
            status.byted_acrawler !== "object" ||
            status.sign !== "function"
        ) {
            throw new Error(
                "window.byted_acrawler.sign is not available"
            );
        }

        await this.page.evaluate(() => {
            window.__generateTikTokSignature =
                function(url) {
                    if (
                        !window.byted_acrawler ||
                        typeof window.byted_acrawler.sign !== "function"
                    ) {
                        throw new Error(
                            "byted_acrawler.sign unavailable"
                        );
                    }

                    return window.byted_acrawler.sign({
                        url: url
                    });
                };
        });

        console.log(
            "[SIGN] Signer initialization complete."
        );
    }

    async navigator() {
        if (!this.page) {
            throw new Error(
                "Signer is not initialized"
            );
        }

        return await this.page.evaluate(() => {
            return {
                deviceScaleFactor:
                    window.devicePixelRatio,

                user_agent:
                    window.navigator.userAgent,

                browser_language:
                    window.navigator.language,

                browser_platform:
                    window.navigator.platform,

                browser_name:
                    window.navigator.appCodeName,

                browser_version:
                    window.navigator.appVersion
            };
        });
    }

    async sign(link) {
        if (!this.page) {
            throw new Error(
                "Signer is not initialized"
            );
        }

        console.log(
            "[SIGN] Generating signature..."
        );

        const verify_fp =
            Utils.generateVerifyFp();

        const separator =
            link.includes("?") ? "&" : "?";

        const newUrl =
            link +
            separator +
            "verifyFp=" +
            encodeURIComponent(verify_fp);

        let token;

        try {
            token = await this.page.evaluate(
                (url) => {
                    return window.__generateTikTokSignature(
                        url
                    );
                },
                newUrl
            );
        } catch (err) {
            console.error(
                "[SIGN] Signature generation failed:"
            );

            console.error(err);

            throw err;
        }

        if (!token) {
            throw new Error(
                "Empty TikTok signature"
            );
        }

        const signed_url =
            newUrl +
            "&_signature=" +
            encodeURIComponent(token);

        const queryString =
            new URL(signed_url)
                .searchParams
                .toString();

        let bogus = "";

        try {
            const hasBogus =
                await this.page.evaluate(() => {
                    return (
                        typeof window.generateBogus ===
                        "function"
                    );
                });

            if (hasBogus) {
                bogus = await this.page.evaluate(
                    ({ params, ua }) => {
                        return window.generateBogus(
                            params,
                            ua
                        );
                    },
                    {
                        params: queryString,
                        ua: this.userAgent
                    }
                );
            }
        } catch (err) {
            console.warn(
                "[SIGN] X-Bogus failed:",
                err.message
            );
        }

        let finalUrl = signed_url;

        if (bogus) {
            finalUrl +=
                "&X-Bogus=" +
                encodeURIComponent(bogus);
        }

        console.log(
            "[SIGN] Signature generated."
        );

        return {
            signature: token,
            verify_fp: verify_fp,
            signed_url: finalUrl,
            "x-tt-params":
                this.xttparams(queryString),
            "x-bogus": bogus
        };
    }

    xttparams(query_str) {
        query_str += "&is_encryption=1";

        const cipher =
            createCipheriv(
                "aes-128-cbc",
                this.password,
                this.password
            );

        return Buffer.concat([
            cipher.update(query_str),
            cipher.final()
        ]).toString("base64");
    }

    async close() {
        try {
            if (
                this.browser &&
                !this.isExternalBrowser
            ) {
                await this.browser.close();
            }
        } catch (_) {}

        this.browser = null;
        this.context = null;
        this.page = null;
    }
}

module.exports = Signer;

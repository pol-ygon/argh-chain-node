import requests
import statistics

URL_XRAY = "https://services.swpc.noaa.gov/json/goes/primary/xrays-1-day.json"
# flare: A B C -> mint
# flare: M X   -> burn

URL_XRAY_BG = "https://services.swpc.noaa.gov/json/goes/primary/xray-background-7-day.json"
# used to manage staking rewards low value + gain high value - gain

URL_MAGNETOMETERS = "https://services.swpc.noaa.gov/json/goes/primary/magnetometers-1-day.json"
# used as a mint reducer can make mint + or - based on the values ​​of the magnetometers

class FlareSource:
    def get_latest(self):
        print("🌐 Fetching Flares API...")
        try:
            data_xray = requests.get(URL_XRAY, timeout=5).json()
            data_bg = requests.get(URL_XRAY_BG, timeout=5).json()
            data_mag = requests.get(URL_MAGNETOMETERS, timeout=5).json()

            # filters ONLY 0.05–0.4nm
            filtered_xray = [
                e for e in data_xray
                if e.get("energy") == "0.05-0.4nm"
            ]

            if not filtered_xray:
                return None

            latest_xray = filtered_xray[-1]

            # MAGNETOMETERS: Take last N minutes
            totals = [
                e["total"] for e in data_mag[-60:]
                if "total" in e and e.get("arcjet_flag") is False
            ]

            geomag_sigma = (
                statistics.stdev(totals)
                if len(totals) >= 2
                else 0.0
            )

            geomag_factor = self.geomag_factor_from_sigma(geomag_sigma)

            return {
                "xray": latest_xray,
                "geomag_sigma": geomag_sigma,
                "geomag_factor": geomag_factor
            }

        except Exception as e:
            print("FlareSource error:", e)
            return None

    
    def geomag_factor_from_sigma(self, sigma):
        if sigma < 0.2:
            return 1.0      # noise → neutral
        if sigma < 0.5:
            return 1.3      # calm → boost mint
        if sigma < 2:
            return 1.0      # normal
        if sigma < 5:
            return 0.7      # disturbed
        if sigma < 15:
            return 0.3      # storm
        return -0.5         # severe storm → burn
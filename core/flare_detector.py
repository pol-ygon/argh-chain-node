import math
from datetime import datetime

class Flare:
    def __init__(self, fid, cls, flux, ts):
        self.id = fid
        self.cls = cls
        self.flux = flux
        self.ts = ts

class FlareDetector:
    def __init__(self):
        self.seen = set()

    def classify(self, flux):
        if flux < 1e-7: return "A"
        if flux < 1e-6: return "B"
        if flux < 1e-5: return "C"
        if flux < 1e-4: return "M"
        return "X"

    def flare_id(self, event):
        ts = event["time_tag"]
        flux = event["flux"]

        # math protection
        if flux is None or flux <= 0:
            return None

        cls = self.classify(flux)
        bucket = round(math.log10(flux), 1)
        dt = datetime.fromisoformat(ts.replace("Z", ""))

        return f"{cls}-{dt.strftime('%Y%m%d%H%M')}-{bucket}"

    def process(self, event):
        fid = self.flare_id(event)

        # invalid flare
        if fid is None:
            return None

        if fid in self.seen:
            return None

        self.seen.add(fid)

        flux = event["flux"]
        cls = self.classify(flux)

        return Flare(
            fid=fid,
            cls=cls,
            flux=flux,
            ts=event["time_tag"]
        )

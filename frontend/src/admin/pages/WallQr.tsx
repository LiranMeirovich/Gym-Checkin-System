// The printable wall QR, for the owner and managers (settings.edit;
// decision 0051), opened from the Settings screen. The QR always opens
// https://<GYM_PUBLIC_HOSTNAME>/c: the server builds both the address and
// the picture, so nothing here works out a URL. Printing shows only the
// poster: the gym's logo or name, the QR, one line of text and the address.

import { useQuery } from "@tanstack/react-query";
import { Link } from "react-router";
import { api, type Schemas } from "../backend/client";
import { useBranding } from "../branding";
import ui from "../layout/ui.module.css";
import { Brand } from "../../shared/Brand";
import { NoConnection } from "../../shared/NoConnection";
import styles from "./WallQr.module.css";

type WallQr = Schemas["WallQrAnswer"];

/** The server refused: this role can't open the page. */
class Forbidden extends Error {}

async function fetchWallQr(): Promise<WallQr> {
  const { data, response } = await api.GET("/api/wall-qr");
  if (data) return data;
  if (response.status === 403) throw new Forbidden();
  throw new Error(`GET /api/wall-qr failed: ${response.status}`);
}

export function WallQr() {
  const branding = useBranding();
  const wallQr = useQuery({
    queryKey: ["wall-qr"],
    queryFn: fetchWallQr,
    // No retries: a refusal won't change, and each request counts as
    // activity for the auto-lock.
    retry: false,
  });
  // Both are null together: no public hostname set (dev only).
  const poster =
    wallQr.data?.url != null && wallQr.data.qr_image != null
      ? { url: wallQr.data.url, image: wallQr.data.qr_image }
      : null;

  return (
    // No <main> here: the headerless layout's <main> holds this.
    <>
      <div className={styles.toolbar}>
        <Link className={ui.back} to="/settings">
          חזרה להגדרות
        </Link>
        {poster && (
          <button
            type="button"
            className={ui.primary}
            onClick={() => window.print()}
          >
            הדפסה
          </button>
        )}
      </div>

      {wallQr.isPending ? null : wallQr.error instanceof Forbidden ? (
        <p role="alert">הדף פתוח למנהלים בלבד.</p>
      ) : wallQr.isError ? (
        <NoConnection />
      ) : poster == null ? (
        <p role="alert">
          הכתובת הציבורית לא הוגדרה בשרת (GYM_PUBLIC_HOSTNAME), ולכן אין קוד
          להדפסה.
        </p>
      ) : (
        <section className={styles.poster} aria-label="הדף להדפסה">
          <Brand branding={branding} size="hero" />
          <img
            className={styles.qr}
            src={poster.image}
            alt="קוד QR לכניסה למכון"
          />
          <p className={styles.instruction}>
            סרקו את הקוד במצלמה של הטלפון כדי להיכנס
          </p>
          <p className={styles.address}>
            <span dir="ltr">{poster.url}</span>
          </p>
        </section>
      )}
    </>
  );
}

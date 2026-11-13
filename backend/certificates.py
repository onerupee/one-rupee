"""Printable one-page A4 PDF certificates for verified One Rupee members."""

from datetime import datetime
from html import escape
from pathlib import Path
import re
from playwright.sync_api import sync_playwright


CERTIFICATE_DIR = Path.home() / ".one_rupee" / "certificates"


def generate_certificate(
    member_id: int,
    order_id: str,
    name: str = None,
) -> str:
    """Create a printable A4 landscape PDF certificate."""

    CERTIFICATE_DIR.mkdir(
        parents=True,
        exist_ok=True,
    )

    safe_order_id = re.sub(
        r"[^A-Za-z0-9_-]",
        "_",
        order_id,
    )

    certificate_path = (
        CERTIFICATE_DIR
        / f"member-{member_id}-{safe_order_id}.pdf"
    )

    if certificate_path.exists():
        return str(certificate_path)

    html_content = _certificate_html(
        member_id,
        order_id,
        name,
    )

    with sync_playwright() as playwright:
        browser = playwright.chromium.launch()

        try:
            page = browser.new_page()

            page.set_content(
                html_content,
                wait_until="networkidle",
            )

            page.evaluate("document.fonts.ready")

            page.pdf(
                path=str(certificate_path),
                format="A4",
                landscape=True,
                print_background=True,
                prefer_css_page_size=True,
            )

        finally:
            browser.close()

    return str(certificate_path)


def _certificate_html(
    member_id: int,
    order_id: str,
    name: str = None,
) -> str:

    display_name = (
        escape(name.strip())
        if name and name.strip()
        else "MYSTERY MEMBER"
    )

    escaped_order_id = escape(order_id)

    date_text = datetime.now().strftime(
        "%d/%m/%Y"
    )

    return f"""<!DOCTYPE html>
<html lang="en">

<head>

<meta charset="UTF-8">

<meta
    name="viewport"
    content="width=device-width, initial-scale=1.0"
>

<title>
One Rupee Certificate — Member #{member_id}
</title>

<link rel="preconnect" href="https://fonts.googleapis.com">
<link href="https://fonts.googleapis.com/css2?family=Fraunces:ital,wght@0,600;0,900;1,600&family=Space+Grotesk:wght@500;700&display=swap" rel="stylesheet">

<style>

/* ================================
   PAGE SETUP
   ================================ */

@page {{
    size: A4 landscape;
    margin: 0;
}}


* {{
    box-sizing: border-box;
}}


html,
body {{
    font-family: 'Space Grotesk', Arial, Helvetica, sans-serif;

    /* Warm charcoal backdrop with a soft gold glow — no clashing neon. */
    background:
        radial-gradient(
            circle at 15% 20%,
            rgba(212, 175, 55, .18) 0%,
            transparent 40%
        ),
        radial-gradient(
            circle at 85% 80%,
            rgba(212, 175, 55, .12) 0%,
            transparent 45%
        ),
        linear-gradient(
            135deg,
            #14110f 0%,
            #241d16 100%
        );

    display: flex;
    justify-content: center;
    align-items: center;

    padding: 8mm;

    margin: 0;
    min-height: 100vh;
    min-height: 100dvh;
}}


/* ================================
   A4 CERTIFICATE
   ================================ */

.certificate {{

    width: 281mm;

    height: 194mm;

    max-width: 100%;

    position: relative;

    overflow: hidden;

    padding: 10mm 14mm;

    text-align: center;

    background:
        radial-gradient(
            circle at 10% 12%,
            rgba(212, 175, 55, .10) 0%,
            transparent 30%
        ),
        radial-gradient(
            circle at 92% 90%,
            rgba(212, 175, 55, .10) 0%,
            transparent 32%
        ),
        linear-gradient(
            160deg,
            #fdfbf5 0%,
            #f7f2e4 100%
        );

    border: 1.2mm solid #b5892f;

    border-radius: 6mm;

    box-shadow:
        0 0 0 2mm #fdfbf5,
        0 0 0 2.6mm #b5892f,
        0 6mm 18mm rgba(0, 0, 0, .45);

    display: flex;

    flex-direction: column;

    align-items: center;
}}


/* Decorative corner flourishes */

.certificate::before {{

    content: "";

    position: absolute;

    top: -30mm;

    left: -30mm;

    width: 90mm;

    height: 90mm;

    border-radius: 50%;

    background: radial-gradient(circle, rgba(181, 137, 47, .16) 0%, transparent 70%);
}}


.certificate::after {{

    content: "₹1";

    position: absolute;

    right: -10mm;

    bottom: -16mm;

    width: 46mm;

    height: 46mm;

    display: grid;

    place-items: center;

    border-radius: 50%;

    background: transparent;

    border: 1.5mm solid #b5892f;

    color: #b5892f;

    font-family: 'Fraunces', serif;

    font-size: 13mm;

    font-weight: 900;

    opacity: .16;

    transform: rotate(-10deg);
}}


/* ================================
   HEADER
   ================================ */

.top-badge {{

    display: inline-block;

    padding: 2mm 9mm;

    background: #1c1712;

    color: #e9c873;

    border-radius: 8mm;

    font-size: 3.6mm;

    font-weight: 700;

    letter-spacing: .6mm;

    text-transform: uppercase;

    border: .3mm solid #b5892f;
}}


h1 {{

    margin: 5mm 0 2mm;

    font-family: 'Fraunces', serif;

    font-size: 24mm;

    line-height: .9;

    font-weight: 900;

    font-style: italic;

    color: #1c1712;

    letter-spacing: .5mm;
}}


.subtitle {{

    margin: 1mm 0 4mm;

    padding: 1.5mm 9mm;

    color: #7a5c1e;

    border-top: .3mm solid #d3b56a;

    border-bottom: .3mm solid #d3b56a;

    font-size: 5mm;

    font-weight: 700;

    letter-spacing: 1mm;

    text-transform: uppercase;
}}


/* ================================
   NAME + MEMBER
   ================================ */

.presented {{

    color: #8a6a24;

    font-size: 3.4mm;

    font-weight: 700;

    letter-spacing: 1.2mm;

    text-transform: uppercase;

    margin-top: 1mm;
}}


.name {{

    display: inline-block;

    margin: 2mm auto 2mm;

    padding: 1.5mm 8mm 3mm;

    max-width: 80%;

    background: transparent;

    color: #1c1712;

    border-bottom: .6mm solid #b5892f;

    font-family: 'Fraunces', serif;

    font-size: 10mm;

    line-height: 1;

    font-weight: 700;

    overflow-wrap: anywhere;
}}


.member {{

    margin: 1mm 0 3mm;

    color: #7a5c1e;

    font-size: 5mm;

    font-weight: 700;

    letter-spacing: .3mm;
}}


/* ================================
   DESCRIPTION
   ================================ */

.description {{

    max-width: 210mm;

    margin: 0 auto 3mm;

    font-size: 4mm;

    line-height: 1.3;

    font-weight: 500;

    color: #3a2f22;
}}


.description strong {{

    color: #a3781f;

    font-size: 1.1em;
    font-weight: 700;
}}


/* ================================
   MEME GRID
   ================================ */

.meme-grid {{

    width: 100%;

    display: grid;

    grid-template-columns:
        repeat(4, 1fr);

    gap: 3mm;

    margin: 2mm 0;

}}


.meme {{

    min-height: 39mm;

    padding: 3.5mm;

    border: .3mm solid #d3b56a;

    border-radius: 3mm;

    text-align: left;

    background: #fffdf7;

    box-shadow: 0 1mm 3mm rgba(0, 0, 0, .06);
}}


.meme h2 {{

    margin: 0 0 1.5mm;

    font-size: 3.8mm;

    line-height: 1.1;

    font-weight: 700;

    color: #1c1712;

    letter-spacing: .2mm;
}}


.meme p {{

    margin: 0;

    font-size: 3.1mm;

    line-height: 1.3;

    font-weight: 500;

    color: #4a3f30;
}}


.meme strong {{
    font-weight: 700;
    color: #a3781f;
}}


.meme.accent-a {{
    border-top: 1mm solid #b5892f;
}}


.meme.accent-b {{
    border-top: 1mm solid #6b7d5c;
}}


.meme.accent-c {{
    border-top: 1mm solid #a3562f;
}}


.meme.accent-d {{
    border-top: 1mm solid #3d6b7a;
}}


/* ================================
   BOTTOM ACHIEVEMENT
   ================================ */

.achievement {{

    width: 100%;

    padding: 3.5mm 6mm;

    margin: 2mm 0;

    background: #1c1712;

    color: #f7f2e4;

    border-radius: 3mm;

    display: flex;

    justify-content: center;

    align-items: center;

    gap: 8mm;

    flex-wrap: wrap;
}}


.achievement h2 {{

    margin: 0;

    font-size: 4mm;

    color: #e9c873;

    letter-spacing: .3mm;
}}


.achievement p {{

    margin: 0;

    font-size: 3.5mm;

    font-weight: 700;
}}


/* ================================
   FOOTER ROW
   ================================ */

.bottom-row {{

    width: 100%;

    display: flex;

    justify-content: space-between;

    align-items: center;

    margin-top: 3mm;

    padding: 0 5mm;
}}


.date-box {{

    font-size: 3.5mm;

    font-weight: 700;

    color: #3a2f22;
}}


.date-box span {{

    color: #a3781f;
    font-weight: 700;
}}


.order {{

    margin: 0;

    max-width: 100mm;

    font-size: 2.5mm;

    color: #8a7f6c;

    overflow-wrap: anywhere;
}}


.footer {{

    padding: 2mm 8mm;

    background: transparent;

    color: #7a5c1e;

    border: .3mm solid #d3b56a;

    border-radius: 5mm;

    font-size: 3.4mm;

    font-weight: 700;

    letter-spacing: .2mm;
}}


/* ================================
   PRINT BUTTON
   ================================ */

.print-button {{

    margin-top: 4mm;

    padding: 2.5mm 7mm;

    border: 0;

    border-radius: 5mm;

    background: #1c1712;

    color: #e9c873;

    font-size: 3.2mm;

    font-weight: 700;

    letter-spacing: .3mm;

    cursor: pointer;
}}


.print-button:hover {{
    background: #34291b;
}}


/* ================================
   PRINT MODE
   ================================ */

@media print {{

    html,
    body {{

        width: 297mm;

        height: 210mm;

        margin: 0;

        padding: 0;

        background: white;
    }}

    body {{

        display: block;
    }}

    .certificate {{

        width: 281mm;

        height: 194mm;

        margin: 8mm;

        box-shadow: none;

        border-radius: 5mm;

        page-break-after: avoid;

        page-break-before: avoid;
    }}

    .print-button {{
        display: none;
    }}
}}


/* ================================
   TABLET / LAPTOP SCREENS
   (below A4-landscape's natural size)
   ================================ */

@media screen and (min-width: 901px) {{

    body {{
        padding: 3vmin;
        align-items: flex-start;
    }}

    .certificate {{
        width: min(281mm, 96vw);
        height: auto;
        padding: min(10mm, 2.2vh) min(14mm, 2.6vw);
    }}
}}


/* ================================
   SMALL SCREEN VIEW
   ================================ */

@media screen and (max-width: 900px) {{

    html,
    body {{
        min-height: auto;
        height: auto;
        background-attachment: fixed;
    }}

    body {{
        align-items: flex-start;
        padding: 16px 12px;
    }}

    .certificate {{

        width: 100%;

        height: auto;

        min-height: auto;

        padding: 30px 20px 24px;

        border-radius: 20px;

        box-shadow:
            0 0 0 6px #fdfbf5,
            0 0 0 8px #b5892f,
            0 10px 30px rgba(0, 0, 0, .45);
    }}

    .certificate::before {{
        width: 220px;
        height: 220px;
        top: -70px;
        left: -70px;
    }}

    .certificate::after {{
        width: 130px;
        height: 130px;
        font-size: 34px;
        right: -30px;
        bottom: -35px;
    }}

    .top-badge {{
        padding: 6px 18px;
        font-size: 11px;
    }}

    h1 {{
        font-size: 42px;
        margin: 14px 0 6px;
        white-space: nowrap;
    }}

    .subtitle {{
        font-size: 16px;
        padding: 5px 18px;
    }}

    .presented {{
        font-size: 11px;
    }}

    .name {{
        font-size: 30px;
        max-width: 95%;
        padding: 4px 16px 8px;
    }}

    .member {{
        font-size: 18px;
    }}

    .description {{
        font-size: 14px;
        max-width: 100%;
    }}

    .meme-grid {{

        grid-template-columns:
            repeat(2, 1fr);

        gap: 10px;
    }}

    .meme {{
        min-height: 0;
        padding: 12px;
    }}

    .meme h2 {{
        font-size: 15px;
    }}

    .meme p {{
        font-size: 12.5px;
    }}

    .achievement {{

        flex-direction: column;

        gap: 8px;

        padding: 14px 16px;
    }}

    .achievement h2 {{
        font-size: 15px;
    }}

    .achievement p {{
        font-size: 13px;
    }}

    .bottom-row {{
        flex-direction: column;
        align-items: flex-start;
        gap: 10px;
        padding: 0;
    }}

    .date-box {{
        font-size: 13px;
    }}

    .footer {{
        font-size: 13px;
        padding: 6px 16px;
    }}

    .order {{
        font-size: 10px;
        max-width: 100%;
    }}

    .print-button {{
        margin-top: 16px;
        padding: 10px 24px;
        font-size: 13px;
    }}
}}

</style>

</head>


<body>


<main class="certificate">


    <!-- HEADER -->

    <div class="top-badge">

        🪙 World's Most Unnecessary Achievement

    </div>


    <h1>

        One Rupee

    </h1>


    <div class="subtitle">

        Certificate of Participation

    </div>


    <!-- NAME -->

    <div class="presented">

        Proudly Presented To

    </div>


    <div class="name">

        {display_name}

    </div>


    <div class="member">

        🏆 Member #{member_id}

    </div>


    <!-- DESCRIPTION -->

    <div class="description">

        For voluntarily paying

        <strong>₹1</strong>

        to participate in an experiment

        that absolutely

        <strong>did not need to exist!</strong>

    </div>


    <!-- MEMES -->

    <section class="meme-grid">


        <div class="meme accent-a">

            <h2>

                💸 You Paid ₹1

            </h2>

            <p>

                Nobody forced you.<br>
                Nobody stopped you.<br>
                You looked at ₹1 and said:<br><br>

                <strong>
                    "Yeah. I'll spend that."
                </strong>

                <br><br>

                Legend.

            </p>

        </div>


        <div class="meme accent-b">

            <h2>

                ⚠️ Side Effects

            </h2>

            <p>

                • Zero knowledge gained<br>
                • 100% fun achieved<br>
                • Unlimited flexing<br>
                • Wallet slightly offended<br>
                • Eternal regret

            </p>

        </div>


        <div class="meme accent-c">

            <h2>

                🧠 Brain Status

            </h2>

            <p>

                Brain:
                "Why did we do this?"

                <br><br>

                Heart:
                "Because it was funny."

                <br><br>

                Wallet:
                "I trusted you."

            </p>

        </div>


        <div class="meme accent-d">

            <h2>

                🏅 Membership

            </h2>

            <p>

                You receive absolutely nothing.

                <br><br>

                Except:

                <br>

                ✔ This certificate<br>
                ✔ Bragging rights<br>
                ✔ Member status<br>
                ✔ The ability to say:

                <br><br>

                <strong>
                    "I paid ₹1 for this."
                </strong>

            </p>

        </div>


    </section>


    <!-- ACHIEVEMENT -->

    <section class="achievement">

        <h2>

            🏆 Achievement Unlocked

        </h2>

        <p>

            💰 Gave ₹1 for no reason

        </p>

        <p>

            +999 Fun Points

        </p>

        <p>

            🎖️ Financial damage: minimal

        </p>

    </section>


    <!-- BOTTOM -->

    <div class="bottom-row">


        <div class="date-box">

            📅 Date of greatness:

            <span>

                {date_text}

            </span>

        </div>


        <div class="footer">

            😂 Congratulations! You made ₹1 interesting.

        </div>


        <p class="order">

            Verified Cashfree order:<br>

            <strong>

                {escaped_order_id}

            </strong>

        </p>


    </div>


    <button
        class="print-button"
        onclick="window.print()"
    >

        🖨️ Print this historical document

    </button>


</main>


</body>

</html>
"""

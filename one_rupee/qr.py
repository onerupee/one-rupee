import qrcode


def generate_terminal_qr(url):
    qr = qrcode.QRCode(
        error_correction=qrcode.constants.ERROR_CORRECT_L,
        box_size=1,
        border=1,
    )

    qr.add_data(url)
    qr.make(fit=True)

    matrix = qr.get_matrix()

    # Make the number of rows even.
    if len(matrix) % 2:
        matrix.append([False] * len(matrix[0]))

    # Two QR rows are displayed as one terminal row.
    for y in range(0, len(matrix), 2):

        top = matrix[y]
        bottom = matrix[y + 1]

        line = []

        for t, b in zip(top, bottom):

            if t and b:
                line.append("█")

            elif t:
                line.append("▀")

            elif b:
                line.append("▄")

            else:
                line.append(" ")

        print("".join(line).rstrip())
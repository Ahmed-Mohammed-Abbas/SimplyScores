#!/bin/sh
# SimplyScores installer / updater for Enigma2 receivers. Plugin by reali22.
# Telnet/SSH:
#   wget -q --no-check-certificate https://raw.githubusercontent.com/Ahmed-Mohammed-Abbas/SimplyScores/main/installer.sh -O - | /bin/sh

RAW="https://raw.githubusercontent.com/Ahmed-Mohammed-Abbas/SimplyScores/main"
PACKAGE="enigma2-plugin-extensions-simplyscores"

fetch() {   # fetch URL FILE
    if command -v wget >/dev/null 2>&1; then
        wget -q --no-check-certificate "$1" -O "$2" && return 0
    fi
    if command -v curl >/dev/null 2>&1; then
        curl -k -s -L "$1" -o "$2" && return 0
    fi
    return 1
}

echo "SimplyScores installer (plugin by reali22)"
TMPV=/tmp/simplyscores_version.txt
if ! fetch "$RAW/version.txt?t=$(date +%s)" "$TMPV"; then
    echo "Could not reach GitHub. Check the receiver's internet connection."
    exit 1
fi
VERSION=$(head -n 1 "$TMPV" | tr -d '\r ' | sed 's/^v//')
rm -f "$TMPV"
case "$VERSION" in
    [0-9]*.[0-9]*) ;;
    *) echo "version.txt on GitHub is not readable"; exit 1 ;;
esac

INSTALLED=$(opkg list-installed 2>/dev/null | grep "^$PACKAGE " | awk '{print $3}')
if [ -n "$INSTALLED" ]; then
    echo "Installed: $INSTALLED   Latest: $VERSION"
else
    echo "Installing SimplyScores $VERSION"
fi

IPK="${PACKAGE}_${VERSION}_all.ipk"
cd /tmp || exit 1
rm -f "/tmp/$IPK"
if ! fetch "$RAW/ipk/$IPK" "/tmp/$IPK" || [ ! -s "/tmp/$IPK" ]; then
    echo "Download of $IPK failed."
    rm -f "/tmp/$IPK"
    exit 1
fi

# python3-requests comes from the image's feed when it is missing
python3 -c "import requests" >/dev/null 2>&1 || { opkg update >/dev/null 2>&1; opkg install python3-requests; }

if ! opkg install --force-reinstall --force-downgrade "/tmp/$IPK"; then
    echo "opkg could not install $IPK"
    rm -f "/tmp/$IPK"
    exit 1
fi
rm -f "/tmp/$IPK"

echo ""
echo "SimplyScores $VERSION installed. Restarting the GUI..."
sleep 2
killall -9 enigma2 >/dev/null 2>&1
exit 0

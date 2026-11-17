#!/bin/bash
# Export each sensor's raw readings from InfluxDB, one CSV per sensor and window.
# Run on the gateway laptop, in the folder that has compose.yaml:
#
#   ./export_sensors.sh                            asks for the name, start and end
#   ./export_sensors.sh <name> "<start>" "<end>"   or give them on the command line
#   e.g. ./export_sensors.sh test "2026-11-17 14:00" "2026-11-17 16:30"
#        -> temp_test.csv, iaq_test.csv ... hum_test.csv
#
# Times are IST. Raw readings are kept 7 days: export before they expire.

export TZ=Asia/Kolkata
if [ $# -eq 3 ]; then
  LABEL=$1; START=$2; END=$3
elif [ $# -eq 0 ]; then
  read -rp "name (e.g. test, day1): " LABEL
  read -rp "start (YYYY-MM-DD HH:MM): " START
  read -rp "end   (YYYY-MM-DD HH:MM): " END
else
  echo "usage: $0                               (asks for name, start, end)"
  echo "       $0 <name> \"<start>\" \"<end>\"  e.g. $0 test \"2026-11-17 14:00\" \"2026-11-17 16:30\""
  exit 1
fi

[[ "$LABEL" =~ ^[A-Za-z0-9_]+$ ]] || { echo "name must be letters, numbers or _ (no spaces): '$LABEL'"; exit 1; }
iso() { [ -n "$1" ] && date -d "$1" --iso-8601=seconds 2>/dev/null; }
FROM=$(iso "$START") || { echo "bad start time: '$START' (use YYYY-MM-DD HH:MM)"; exit 1; }
TO=$(iso "$END")     || { echo "bad end time: '$END' (use YYYY-MM-DD HH:MM)"; exit 1; }
[ "$(date -d "$FROM" +%s)" -lt "$(date -d "$TO" +%s)" ] || { echo "start must be before end"; exit 1; }
WINDOWS=("$LABEL|$FROM|$TO")

# sensor uid -> file name prefix
declare -A NAME=(
  [1:1]=temp     [1:2]=iaq      [1:3]=pir      [1:4]=anemo
  [1:6]=Co2      [1:7]=lux      [1:8]=sound    [1:9]=dist
  [1:10]=reed    [1:11]=sct     [1:14]=ctouch  [1:15]=rs485
  [1:16]=appliance               [1:17]=hum
)
ORDER="1:1 1:2 1:3 1:4 1:6 1:7 1:8 1:9 1:10 1:11 1:14 1:15 1:16 1:17"

OUT="datasets"
mkdir -p "$OUT"
Q() { docker compose exec -T influxdb influx -database aiot_blp -format csv \
        -precision rfc3339 -execute "$1"; }

for w in "${WINDOWS[@]}"; do
  IFS='|' read -r SUFFIX FROM TO <<< "$w"
  echo "== $SUFFIX: $FROM  ->  $TO"
  for uid in $ORDER; do
    f="$OUT/${NAME[$uid]}_${SUFFIX}.csv"
    Q "SELECT * FROM \"raw\".\"readings\" WHERE \"sensor_uid\" = '$uid' \
       AND time >= '$FROM' AND time < '$TO' tz('Asia/Kolkata')" > "$f"
    # drop the columns that belong to other sensors (empty in every row)
    python3 - "$f" <<'PY'
import csv, sys
p = sys.argv[1]
rows = list(csv.reader(open(p, newline="")))
if len(rows) > 1:
    keep = [i for i in range(len(rows[0])) if any(r[i] for r in rows[1:] if i < len(r))]
    with open(p, "w", newline="") as fh:
        csv.writer(fh).writerows([[r[i] if i < len(r) else "" for i in keep] for r in rows])
PY
    rows=$(( $(wc -l < "$f") - 1 )); [ "$rows" -lt 0 ] && rows=0
    printf '   %-5s %-22s %7s rows\n' "$uid" "$(basename "$f")" "$rows"
  done
done
echo "files in: $OUT/"

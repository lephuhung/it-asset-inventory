#!/bin/sh
set -eu

cert_dir=/certs

if [ -f "$cert_dir/server.crt" ] && [ -f "$cert_dir/server.key" ]; then
    exit 0
fi

apk add --no-cache openssl >/dev/null
mkdir -p "$cert_dir"
touch "$cert_dir/index.txt"
printf '1000\n' > "$cert_dir/serial"
printf '1000\n' > "$cert_dir/crlnumber"

openssl req -x509 -newkey rsa:2048 -nodes -days 30 \
    -keyout "$cert_dir/issuing-ca.key" \
    -out "$cert_dir/issuing-ca.crt" \
    -subj '/CN=Asset Inventory Development CA' \
    -addext 'basicConstraints=critical,CA:true' >/dev/null 2>&1

openssl req -newkey rsa:2048 -nodes \
    -keyout "$cert_dir/server.key" \
    -out "$cert_dir/server.csr" \
    -subj '/CN=inventory.local' >/dev/null 2>&1
printf '%s\n' \
    'basicConstraints=critical,CA:false' \
    'subjectAltName=DNS:localhost,DNS:inventory.local,DNS:agent.inventory.local' \
    'keyUsage=critical,digitalSignature,keyEncipherment' \
    'extendedKeyUsage=serverAuth' > "$cert_dir/server.ext"
openssl x509 -req -days 30 \
    -in "$cert_dir/server.csr" \
    -CA "$cert_dir/issuing-ca.crt" \
    -CAkey "$cert_dir/issuing-ca.key" \
    -CAcreateserial \
    -out "$cert_dir/server.crt" \
    -extfile "$cert_dir/server.ext" >/dev/null 2>&1

cat > "$cert_dir/ca.conf" <<'EOF'
[ca]
default_ca = CA_default

[CA_default]
database = /certs/index.txt
serial = /certs/serial
crlnumber = /certs/crlnumber
private_key = /certs/issuing-ca.key
certificate = /certs/issuing-ca.crt
default_md = sha256
default_crl_days = 30
EOF
openssl ca -gencrl -batch -config "$cert_dir/ca.conf" \
    -out "$cert_dir/issuing-ca.crl.pem" >/dev/null 2>&1
openssl dhparam -dsaparam -out "$cert_dir/dhparam.pem" 2048 >/dev/null 2>&1
chmod 600 "$cert_dir"/*.key
rm -f "$cert_dir/server.csr" "$cert_dir/server.ext" "$cert_dir/ca.conf"

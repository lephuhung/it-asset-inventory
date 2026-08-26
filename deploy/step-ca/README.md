# Bootstrap step-ca (Internal CA) cho môi trường dev / pilot

step-ca (Smallstep) đóng vai trò **issuing CA** cho mTLS: cấp client cert ECDSA P-256 cho agent lúc enroll, servụ CRL cho nginx.
Root CA nên lưu **offline** (bản thân căn bản bảo mật). Trong dev có thể chạy 1 tiến trình duy nhất cho 2 vai trò.

## 1. Khởi tạo lần đầu (chạy 1 lần, trong container)

Compose canonical: `server/deploy/docker-compose.yml` (postgres :5432, redis :6381, api :8000, nginx :443/:9443).

```bash
cd server/deploy && docker compose run --rm step-ca step ca init \
  --deployment-type standalone \
  --name "Inventory Internal CA" \
  --dns step-ca \
  --address :9000 \
  --provisioner admin \
  --password-file /home/step/pw.txt
```

- Sau init, copy `root_ca.crt` và (issuing) `intermediate_ca.crt` sang `deploy/certs/ca.crt` để nginx dùng làm `ssl_client_certificate`.
- Config provisioner "admin" cho phép API `step ca sign` cấp cert.

## 2. Cấp client cert cho agent (tại lúc enroll)

Agent gửi CSR trong payload enroll. Server gọi API step-ca để ký:

```bash
curl -s -X POST https://step-ca:9000/1.0/sign \
  -H "Authorization: Bearer <provisioner-token>" \
  -d '{"csr":"<base64 PEM>","profile":"client","notBefore":"...","notAfter":"+8760h"}'
```

Trả về cert PEM. Server lưu `cert_serial` vào `machines.cert_serial`, forward `ca_cert_pem` về agent.

## 3. CRL

- Bật CRL trên issuing CA (`STEP_CA_CRL=true`), endpoint `https://step-ca:9000/1.0/crl`.
- Cron định kỳ tải CRL → `deploy/certs/crl.pem`, sau đó `nginx -s reload` (chỉ tải khi có chỉ mục thu hồi).

## 4. Cấu hình nginx

`ssl_client_certificate` trỏ `ca.crt` (bundled root+intermediate), `ssl_verify_client optional`, `ssl_crl /etc/nginx/certs/crl.pem`.
Sau enroll, agent dùng cert này; heartbeat/inventory chỉ được chấp nhận khi `X-SSL-Client-Verify = SUCCESS`.

## Lưu ý MVP

- Trong dev, tạo **self-signed CA tạm** đủ dùng cho demo (script `gen-dev-certs.sh`). Bản pilot thật dùng step-ca thật + khóa trong Vault/KMS.
- Khi triển khai thật: root CA lưu offline, issuing CA chạy trong HSM/KMS, private key không bao giờ trên server ứng dụng.

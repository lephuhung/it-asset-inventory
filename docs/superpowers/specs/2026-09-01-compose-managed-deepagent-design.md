# DeepAgent do Docker Compose quản lý

## Mục tiêu

DeepAgent là một thành phần nội bộ của IT Asset Inventory: chạy trong container riêng, được Docker Compose khởi động cùng API và Portal, và không yêu cầu quản trị viên nhập URL hoặc service token trên giao diện.

## Kiến trúc

`api` và `deepagent` cùng Docker network `asset-inventory-network`. Backend gọi DeepAgent bằng địa chỉ ổn định `http://deepagent:8090`; DeepAgent không publish cổng ra máy chủ. Hai service dùng chung `DEEPAGENT_SERVICE_TOKEN` từ tệp môi trường triển khai. Token không được trả về API Portal hoặc hiển thị trên giao diện.

DeepAgent đóng gói MCP Velociraptor bridge trong image. Khi chạy investigation hoặc kiểm tra, backend đọc cấu hình Velociraptor đã mã hóa trong cơ sở dữ liệu (`URL` và `api_client.yaml`) rồi gửi nó qua mạng Docker nội bộ trong request đã xác thực. DeepAgent dùng YAML này trong tệp tạm thời, chạy MCP bridge với `ENABLE_DANGEROUS_TOOLS=false`, sau đó xóa tệp tạm thời. Nhờ vậy chỉ có một nơi cấu hình Velociraptor: trang DFIR Settings.

## Portal và API

Trang LLM-DFIR không còn trường DeepAgent URL hay DeepAgent service token. Nó chỉ có:

- Công tắc dùng DeepAgent làm orchestrator cho investigation mới.
- Nút **Kiểm tra MCP → Velociraptor**.
- Trạng thái tách bạch: DeepAgent service khả dụng, MCP bridge sẵn sàng, và truy vấn `list_clients(limit=1)` thành công/thất bại.

Backend endpoint kiểm tra lấy YAML từ `VelociraptorConfig`, gọi `GET /health` của service Compose rồi gửi YAML tới endpoint test nội bộ của DeepAgent. Nếu chưa upload YAML, service chưa chạy, bridge không có tool hoặc Velociraptor từ chối kết nối, giao diện hiển thị chẩn đoán theo từng tầng mà không lộ token hay private key.

## Đóng gói và vận hành

Docker Compose thêm service `deepagent`, dependency theo API/Redis khi cần và healthcheck. Docker image DeepAgent bao gồm source bridge đã được khóa dependency. Biến môi trường vận hành cần thiết chỉ gồm token dùng chung, thông tin callback backend và LLM runtime; URL/token vận hành không phải là cấu hình Portal.

## Kiểm thử

- Unit test DeepAgent xác nhận endpoint test nhận YAML tạm, chỉ gọi `list_clients` với giới hạn một.
- Test backend xác nhận endpoint lấy YAML lưu trong DB, không trả secret, và gọi URL nội bộ Compose.
- `docker compose config`, build image API/Portal/DeepAgent và smoke test health.
- Test giao diện xác nhận không còn input URL/token và có nút kiểm tra MCP.

%global debug_package %{nil}

Name:           orginventory-agent
Version:        1.1.0
Release:        1%{?dist}
Summary:        OrgInventory Agent — IT Asset Inventory for Linux
License:        Proprietary
URL:            https://github.com/example/orginventory
Requires:       systemd

%description
IT Asset Inventory Agent — thu thập cấu hình phần cứng, phần mềm và đánh giá
an toàn thông tin ở chế độ chỉ đọc (read-only). Bảo mật mTLS ECDSA P-256.

%install
mkdir -p %{buildroot}/opt/orginventory %{buildroot}/etc/orginventory %{buildroot}%{_unitdir}
cp -r %{_builddir}/orginventory/opt/* %{buildroot}/opt/
install -m 0644 %{_builddir}/orginventory/systemd/orginventory-agent.service %{buildroot}%{_unitdir}/

%pre
getent group orginventory >/dev/null || groupadd -r orginventory
getent passwd orginventory >/dev/null || \
    useradd -r -d /var/lib/orginventory -s /sbin/nologin -G orginventory orginventory

%post
mkdir -p /var/lib/orginventory /var/log/orginventory /run/orginventory
chown -R orginventory:orginventory /var/lib/orginventory /var/log/orginventory /run/orginventory
chmod 0750 /var/lib/orginventory /var/log/orginventory /run/orginventory
systemctl daemon-reload || true
# KHÔNG auto-enable/start — service cần enroll token trước (khớp debian/postinst)

%preun
%systemd_preun orginventory-agent.service

%postun
%systemd_postun orginventory-agent.service

%files
/opt/orginventory
%config /etc/orginventory
%{_unitdir}/orginventory-agent.service

%changelog
* Mon Aug 30 2026 OrgInventory Team <team@example.gov.vn> - 1.1.0-1
- Initial Linux agent release

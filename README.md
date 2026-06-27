# Wi-Fi Auto Reconnect Agent

Windows 10/11에서 Wi-Fi 연결 상태를 주기적으로 감시하고, Wi-Fi가 끊어진 경우에만 `config.json`에 지정된 SSID로 자동 재접속을 시도하는 Python MVP입니다.

이미 어떤 Wi-Fi에 정상 연결되어 있으면 재접속을 시도하지 않습니다.

## Requirements

- Windows 10/11
- Python 3.12+
- 대상 Wi-Fi 프로필이 Windows에 저장되어 있어야 합니다.

## Configuration

`config.json`에서 값을 변경합니다.

```json
{
  "ssid": "CompanyWiFi",
  "check_interval": 5,
  "retry_interval": 5,
  "max_retry": 10
}
```

## Run

```powershell
python main.py
```

백그라운드 실행 예시:

```powershell
Start-Process python -ArgumentList "main.py" -WindowStyle Hidden
```

로그는 `logs/wifi-auto-reconnect.log`에 기록됩니다.

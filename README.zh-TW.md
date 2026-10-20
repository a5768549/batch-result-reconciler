# batch-result-reconciler

只針對**實際提交的 `(row_id, value)` 配對**回填批次結果，不因相同值出現在
其他來源列就擴大回填範圍。

Python 3.11 以上，執行時無第三方相依套件，核心採用標準函式庫 SQLite、JSON
與 SHA-256。[完整英文 API 文件](README.md)

## 安裝與使用

```sh
python -m pip install .
batch-result-reconciler snapshot --rows examples/rows.jsonl --pairs examples/pairs.jsonl --database submission.sqlite3 > manifest.json
batch-result-reconciler reconcile --manifest manifest.json --values examples/returned.jsonl --provider-completed --expected-returned-count 1 > results.jsonl
```

範例均為合成資料。`row-a` 雖然具有相同值，但未提交就不會產生註記。
已提交且有回傳的配對是 `returned`；未回傳的配對是 `not_returned`，**不是 invalid**。
命令亦可透過 `python -m batch_result_reconciler` 執行。

## Python API

```python
from batch_result_reconciler import create_snapshot, reconcile

snapshot = create_snapshot(
    "submission.sqlite3",
    [{"row_id": "row-a", "values": ["item-a", "item-b"], "payload": {"標記": "範例"}}],
    [("row-a", "item-a"), ("row-a", "item-b")],
)
results = list(reconcile(
    snapshot, ["item-a"], provider_completed=True, expected_returned_count=1,
))
```

- 來源列需有 `row_id`、`values` 清單、`payload`。識別碼與值必須是非空字串，
  不會自動修剪空白、轉換大小寫、正規化或轉型。`payload` 可為任意合法 JSON
  值，物件鍵必須是字串，數字不可為 NaN／Infinity。來源物件不會被修改。
- 來源列、提交配對及回傳值可用一次性 iterable。重複來源列 ID、單列內重複值、
  重複配對、重複回傳值及未提交的回傳值均拒絕。相同值可存在不同來源列。
- 一個回傳值可以標註多個已提交配對，`expected_returned_count` 計算的是回傳值
  數量，而非來源列數或配對數。
- 呼叫端必須明確確認供應者已完成，傳入真正的 `True` 與非負整數數量（不接受
  bool 當數量）。空回傳也需 count=0。套件不連線驗證供應者。允許空提交。
- `Snapshot` 是 frozen dataclass，包含 `path`、`sha256`、`source_digest`。
  新 SQLite 檔保存所有來源資料及精確配對；不覆寫既有檔案。提交前請保存描述資訊。
  重新開啟可用 `Snapshot(Path(path), sha256, source_digest)`；不要從可能已改動的
  檔案重新計算「預期」摘要。
- 來源摘要涵蓋正規 JSON 內容、列 ID 與來源值；快照摘要涵蓋整個 SQLite 檔案，
  包含提交範圍。**摘要不是簽章或身分驗證**，預期摘要需由可信任位置保管。
- 回填複製快照到暫存工作檔，先驗證摘要、來源 membership、回傳內容與數量後才
  產生註記；不修改原快照。結果依 `(row_id, value)` 的 SQLite binary 順序輸出，
  每筆包含 `row_id`、`value`、`status`、`payload`。請完整消耗或關閉 generator
  以釋放暫存檔；驗證錯誤發生於迭代時。

## JSON／JSONL 格式

預設 `--input-format jsonl`。來源每行一個 JSON object，配對每行一個兩元素陣列，
回傳值每行一個 JSON 字串（需雙引號），空白行會拒絕，空檔代表空清單。
`--input-format json` 改為讀取整個 JSON 陣列；`--output-format json` 輸出陣列。
CLI 的 Unicode 可能使用跳脫字元，但解碼後內容不變。Manifest 使用絕對路徑，
搬移快照時需更新路徑。重導向請使用 UTF-8 shell；PowerShell 建議 7 以上版本。

驗證失敗 exit=2，錯誤寫入 stderr，輸入驗證失敗不輸出結果註記。Shell 可能已建立
空輸出檔，仍須檢查結束碼。API 驗證錯誤為 `ValueError`，檔案錯誤為 `OSError`
子類別，損壞 SQLite 也可能拋出 `sqlite3.Error`，沒有 fallback。

## 範圍與限制

不是供應者 SDK、正規化引擎、試算表匯出器、認證機制或並行資料庫服務。請使用
呼叫端控制的快照與暫存目錄，不要編輯快照或拿即時 SQLite 資料庫當快照。
核心以磁碟資料表比對，仍需要單筆 payload 與 SQLite buffer 記憶體；CLI JSON
陣列模式會載入完整陣列，JSONL 則逐筆處理。需預留快照及工作複本磁碟空間。
不宣稱 production readiness、效能基準或安全保證。授權 MIT。

## 開發驗證

```sh
python -m pip install ".[test]"
python -m unittest discover -s tests -p "test_smoke_unittest.py" -v
python -m pytest -q
python -m build
```

CI 設定 Ubuntu／Windows、Python 3.11／3.13，測試並建置、安裝 wheel，不發布 PyPI。

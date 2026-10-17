# 微信读书有声书缓存结构

## 路径

```
/data/data/com.tencent.weread/app_data_source/mds_db/<userId>/main/*.ldb
/data/data/com.tencent.weread/app_data_source/mds_db/<userId>/main/*.log
```

- `<userId>` 是形如 `294015443` 的数字目录，一个账号一个；同级的 `common` 目录不含曲目数据。
- 需要 `su` 才能读。`wb.db_dirs()` 会自动探测含 `main/` 的数字目录。
- `.ldb` 是 LevelDB 的 SST 文件，值是明文 JSON（未压缩），可以直接按字节搜字符串。

## key 一览

| key 形态 | 内容 |
|---|---|
| `table#albumInfo#<albumId>` | 专辑元信息：`name` / `trackCount` / `isPodcast` / `authorName` / `cover` |
| `table#trackInfo#TRA_<albumId>_<uid>` | 单集元信息：`title` / `trackIdx` / `trackUid` / `duration` / `trackId` / `payType` |
| `table#trackInfo#local#RemoteTrackSTT#TRA_<albumId>_<uid>` | **AI 文稿**：`text` + `posInfo` |
| `table#album#local#listenRecord` / `lastListenTrackId` | 收听进度，可判断"哪些集听过" |
| `table#trackInfoExtra#TRA_<albumId>_<uid>` | 额外播放统计，取文稿用不到 |

`<uid>` 是 `trackUid`，**不等于**集序号 `trackIdx`。两者都要读 `trackInfo` 才知道对应关系。

## 文稿 JSON 结构

```json
{
  "synckey": 1788315282,
  "text": "第三是情绪化。\n我们太容易被情绪带着跑，\n……",
  "posInfo": [
    {"ms_begin": 620,  "ms_end": 2570,  "pos_end": 7},
    {"ms_begin": 3270, "ms_end": 5820,  "pos_begin": 8,  "pos_end": 20},
    {"ms_begin": 6420, "ms_end": 9170,  "pos_begin": 20, "pos_end": 32}
  ]
}
```

- `text` 用 `\n` 分隔句子；字符位置是 **Python 字符串下标**（可以直接切片）。
- `posInfo` 每条把「音频毫秒区间」映射到「正文字符区间」`[pos_begin, pos_end)`。
- **第一条常常没有 `pos_begin`**，按 0 处理（`wb.norm_pos` 已处理）。
- 最后一条的 `ms_end` 基本等于该集时长，可以用来做兜底匹配。
- 相邻两条的 `pos_end` 与下一条的 `pos_begin` 通常相等，切出来正好是完整句子。

按时间切片就靠这个：给定 `t0`，取第一条 `ms_end > t0` 的 `pos_begin` 作起点；
给定 `t1`，取最后一条 `ms_begin < t1` 的 `pos_end` 作终点。

## 落库条件（关键）

**只有在该集「AI 文稿」页停留过，服务端的转写结果才会写进本地 LevelDB。**
单纯播放、只进播放页都不会写。这就是必须跑 `warm.py` 的原因。

实测：打开文稿页后十几秒到一分钟内落库；有的集打开即可见、有的要等生成。

## 坑一：key 被前缀压缩，按 key 扫不到

LevelDB SST 里同一个 block 的 key 用「共享前缀 + 增量」存储，所以**部分记录的完整 key 字符串并不出现**，
按 `local#RemoteTrackSTT#TRA_<album>_<uid>` 正则只能命中一部分（实测 186 集命中 184）。

兜底做法（`wb.load_stt`）：

1. 收集所有 `{"synckey"` 开头的 JSON，得到「无主」记录池（含别的书的记录）
2. 对没命中 key 的集，用 `|最后一句 ms_end − 曲目时长| ≤ 2500ms` 找候选
3. 再加「字数/秒 ∈ [2.0, 9.0]」过滤（中文朗读大致这个区间）
4. 命中标 `match = "loose"`，`scan.py` 会打印出来让你抽查

**只按时长匹配会串台**：曾有另一本书的单集时长恰好也是 439 秒，被误配成该集文稿。
所以 `loose` 匹配的集**必须人工看一眼开头**——这也是 `scan.py` 把它们单独列出来的原因。

更稳的替代方案：对 `loose` 的集重新跑一次 `warm.py --ep <n>`，
让应用重新写一条**带完整 key** 的记录，再 `--pull` 重建索引。

## 坑二：不是每集都有 AI 文稿

作者/平台可能只为部分集开启转写。`scan.py` 的"缺文稿"列表里如果某集反复补不出来，
基本就是它本身没有文稿，不要再耗时间。

## 文本规律

- 转写是**逐句**的，短句很多（"放下偏见，"独立成句很常见），所以"句数"远大于段落数。
- 会有识别错字（"正新板块"其实是"正心板块"），按原文保留，不要擅自改写。
- 集与集之间是连续的（上集结尾的话可能接着下集开头），拼接时注意不要当成重复内容去重。

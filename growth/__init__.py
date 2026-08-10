"""
Growth Engine — turns the day's published predictions into marketing content.

The rule the whole package is built around: there is exactly one authoritative
prediction dataset, and every channel is a rendering of it. Nothing in here
predicts, scores, prices or selects anything. `dataset.build()` reads what
`leagues.daily_feed` already published and normalises it; everything
downstream renders that.

That constraint is not stylistic. The site had a second, older prediction
pipeline still wired to the Predictions page, and it quietly went blank
because it was no longer being maintained while the leagues engine was. A
marketing channel with its own copy of the selection logic would drift the
same way, except the drift would be published to Telegram and social instead
of a page somebody would notice.
"""

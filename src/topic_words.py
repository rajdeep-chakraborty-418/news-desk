"""Word lists for finding topics in headlines: words that are never topics, and the endings Bengali words take.
Lists are deliberately plain data so they can be extended in external_config/topics/<section>.json ("stopwords")."""

# Bengali function words, common verbs and newsroom filler (compared after the ending is stripped as well)
BENGALI_STOP = """
এবং ও এর এই ওই সেই যে যা কি কী কে না নয় নেই আছে আছেন ছিল ছিলেন হল হলেন হয় হয়ে হবে হবেন হয়েছে হয়েছেন হচ্ছে হচ্ছেন হলে হতে
করে করা করতে করল করলেন করেন করছে করছেন করবে করবেন করেছে করেছেন করায় করার করলে কর
থেকে থেকেই জন্য সঙ্গে সাথে পর পরে আগে আর তাই কিন্তু বলে বলেন বলল বললেন বলা বলছেন জানালেন জানাল জানান জানিয়েছেন জানিয়ে
দিলেন দিল দেন দেয় দেবে দিয়ে দিতে দিয়েছেন দেওয়া দেওয়ার নিয়ে নিল নিলেন নেন নেবে নিতে নেওয়া নেওয়ার গেল গেলেন যায় যাবে যান যাচ্ছে গিয়ে যাওয়া
এল এলেন আসে আসছে আসবে এসে আসা ফের আবার আজ আজকের কাল এখন তখন কত কেন কীভাবে কোথায় কবে কোন কোনও কেউ সব সবাই সকলে সকল
একটি একটা এক দুই তিন চার পাঁচ ছয় সাত আট নয় দশ প্রথম দ্বিতীয় নতুন বড় ছোট বিরুদ্ধে মধ্যে মাঝে ভিতরে ভেতরে উপর ওপর নীচে নিচে জুড়ে পক্ষে মতো মত যেন যদি তবে তো ই সহ প্রায় আরও আরো শুধু কেবল
দিন বছর মাস সময় ঘণ্টা মিনিট খবর খবরের ভিডিয়ো ভিডিও ছবি ছবিতে ফটো লাইভ আপডেট দেখুন দেখে দেখা জানুন জানতে পড়ুন কারণ কারণে ফলে তাঁর তাঁকে তাঁদের তার তাকে তাদের তিনি তাঁরা তারা তা
আমি আমরা আমাদের আমার তুমি আপনি আপনার আপনাকে এঁদের এদের এটি এটা ওটা সেটা এখানে সেখানে যেখানে যখন যত যাঁর যাঁকে যাঁদের
পারে পারেন পারবে পারলেন পেল পেলেন পাবে পান পেয়ে পাওয়া চান চায় চাইছে চাইলেন চাওয়া থাকবে থাকে থাকা থাকলেন রয়েছে রয়েছেন রইল
ঘিরে নিয়ে বিষয়ে প্রসঙ্গে ব্যাপারে বদলে পাশে সামনে পিছনে আগেই পরেই মাত্র ফলে ছাড়া ছাড়াই মধ্যেই পর্যন্ত অবধি বেশি কম বহু অনেক অনেকে কয়েক কিছু কিছুই
এবার মা নাম টাকা বার্তা হাজার বিশেষ দাবি হলো কাছ জের মুখ বাদ কাজ হাত জানেন বিয়ে রায় ঘোষণা অভিযোগ মানুষ বাড়ি গাড়ি জয় ধাক্কা প্রভাব হয়ে এবা নিয় কো মুখ জন লাখ কোটি শুরু শেষ বন্ধ খুলে খুলল চলছে চলবে চলে চালু বাড়ল বাড়ছে কমল কমছে বাড়ে লাগল লাগে ঘটল ঘটনা ঘটনায় হামলা
""".split()

ENGLISH_STOP = """
the a an of in on to for and or with is are was were be by at as it its this that from vs v after before over under about into out up down
live update updates news video videos photo photos watch big breaking today latest viral exclusive top story stories read more new how why what who
when where says say said will can may could not no yes
""".split()

# Case and plural endings, longest first; stripped once, and only from Bengali words (see stem()).
BENGALI_ENDINGS = sorted("""
গুলোকে গুলিকে গুলোর গুলির গুলো গুলি দেরকে দের দেরই রাও কেই কেও কে ের েরা রা তেই তেও তে য়ের য়েও য়ে য়ও য় র ে ই
""".split(), key=len, reverse=True)

# Newsroom filler that is never a topic in English headlines (the section's own list can add more: "stopwords").
ENGLISH_NOISE = """
against across amid among along around between during through while since until within without upon toward towards per via than then also
back return returns returned seeks seek says says said told tells due held hold holds make makes made get gets got take takes took
two three four five six seven eight nine ten first second third last next one day days week weeks month months year years night morning
january february march april may june july august september october november december monday tuesday wednesday thursday friday saturday sunday
rs lakh lakhs crore crores cr usd dollar dollars rupees per cent percent pct mn bn million billion thousand
man men woman women boy girl people person persons family state states city district village town
police court courts govt government minister ministers ceo chief cm hc sc pm leader leaders official officials
report reports reported deal deals talks talk war case cases plan plans bid move moves set sets
new old top big high low more most less least many much some any all both each every other another such own same
warns warn urges urge asks ask demands demand claims claim hits hit sees see shows show gives give takes calls call
up down out off over near ahead behind after before under above below inside outside
may will would should could can must might shall
get gets going goes go come comes came
strike strikes killed kills dead dies die death deaths injured arrested arrest
water power market markets price prices rate rates
world global national international local
jan feb mar apr jun jul aug sep sept oct nov dec class university college school students student bank banks south north east west central
""".split()

# Short names that are written in capitals (shown as US, not Us).
ACRONYMS = set("""us uk eu un uae usa nato ai ipl bjp rbi sebi isro cbi nia gst fir nasa fbi cia imf wto who opec asean brics sc hc
tvk dmk aiadmk tmc ncp sp bsp aap jdu rjd ndtv ani pti ap""".split())

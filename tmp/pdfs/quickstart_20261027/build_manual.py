from pathlib import Path
from xml.sax.saxutils import escape
import json
from PIL import Image as PILImage
from reportlab.pdfgen import canvas
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.lib.colors import HexColor, Color, white
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle
from reportlab.platypus import Paragraph, Table, TableStyle
from pypdf import PdfReader

ROOT = Path(__file__).resolve().parents[3]
WORK = Path(__file__).resolve().parent
ASSETS = WORK / 'assets'
OUT = ROOT / 'output' / 'pdf'
OUT.mkdir(parents=True, exist_ok=True)
TARGET = OUT / '弹簧图纸审图助手_新手使用手册.pdf'
pdfmetrics.registerFont(TTFont('Guide', 'C:/Windows/Fonts/Deng.ttf'))
pdfmetrics.registerFont(TTFont('GuideBold', 'C:/Windows/Fonts/Dengb.ttf'))
pdfmetrics.registerFontFamily('Guide', normal='Guide', bold='GuideBold', italic='Guide', boldItalic='GuideBold')
BLUE, INK, MUTED, LINE = map(HexColor, ['#2452CB', '#172033', '#526176', '#D7DFEB'])
PALE = HexColor('#F1F5FC')
W, H = A4
LEFT, WIDTH = 44, W - 88
styles = {
 'body': ParagraphStyle('body', fontName='Guide', fontSize=10.2, leading=15.4, textColor=INK, wordWrap='CJK', spaceAfter=0),
 'small': ParagraphStyle('small', fontName='Guide', fontSize=8.6, leading=12.5, textColor=MUTED, wordWrap='CJK'),
 'title': ParagraphStyle('title', fontName='GuideBold', fontSize=24, leading=32, textColor=INK, wordWrap='CJK'),
 'sub': ParagraphStyle('sub', fontName='GuideBold', fontSize=13, leading=19, textColor=INK, wordWrap='CJK'),
 'cell': ParagraphStyle('cell', fontName='Guide', fontSize=9.5, leading=14.5, textColor=INK, wordWrap='CJK'),
 'tablehead': ParagraphStyle('tablehead', fontName='GuideBold', fontSize=9.5, leading=14, textColor=INK, wordWrap='CJK'),
}


def crop(name, box, dest):
    im = PILImage.open(ASSETS / f'{name}.png')
    w, h = im.size
    im.crop(tuple(round(v * (w if i % 2 == 0 else h)) for i, v in enumerate(box))).save(ASSETS / f'{dest}.png')


# Crop only empty margins and off-topic areas from screenshots, never edit UI text.
crop('generation', (0, 0, 1, .48), 'generation-detail')
crop('parameter-table', (0, 0, 1, json.loads((ASSETS / 'crop.json').read_text())['parameterBottom']), 'parameter-detail')
crop('sheet', (0, 0, 1, .57), 'sheet-detail')


class Guide:
    def __init__(self):
        self.c = canvas.Canvas(str(TARGET), pagesize=A4, pageCompression=1)
        self.c.setTitle('弹簧图纸 AI 审查助手｜新手使用手册')
        self.c.setAuthor('弹簧图纸 AI 审查助手')
        self.c.setSubject('从首次进入、上传识别、核对确认，到生成和下载图纸的六页操作说明')
        self.page = 0
        self.y = H - 61

    def new(self, title, lead):
        if self.page:
            self.finish()
            self.c.showPage()
        self.page += 1
        self.y = H - 61
        self.c.setFillColor(MUTED)
        self.c.setFont('Guide', 8.5)
        self.c.drawString(LEFT, H - 29, '弹簧图纸 AI 审查助手')
        self.c.drawRightString(W - LEFT, H - 29, '新手使用手册 · 2026.10')
        self.c.setStrokeColor(LINE)
        self.c.line(LEFT, H - 39, W - LEFT, H - 39)
        self.c.bookmarkPage(f'step{self.page}')
        self.c.addOutlineEntry(title, f'step{self.page}', 0)
        self.p(title, 'title', after=7)
        self.p(lead, after=14)

    def reserve(self, height):
        if self.y - height < 48:
            raise ValueError(f'Page {self.page} overflow by {48-(self.y-height):.1f} pt; y={self.y:.1f}, height={height:.1f}')

    def p(self, text, style='body', after=8, x=None, width=None):
        paragraph = Paragraph(text, styles[style])
        pw, ph = paragraph.wrap(width or WIDTH, 1000)
        self.reserve(ph + after)
        paragraph.drawOn(self.c, LEFT if x is None else x, self.y - ph)
        self.y -= ph + after
        return ph

    def heading(self, text):
        self.y -= 3
        self.p(text, 'sub', after=7)

    def step(self, number, title, content):
        y = self.y
        self.c.setFillColor(BLUE)
        self.c.circle(LEFT + 9, y - 9, 9, stroke=0, fill=1)
        self.c.setFillColor(white)
        self.c.setFont('GuideBold', 9.5)
        self.c.drawCentredString(LEFT + 9, y - 12.2, str(number))
        paragraph = Paragraph(f'<b>{title}</b>　{content}', styles['body'])
        _, ph = paragraph.wrap(WIDTH - 31, 1000)
        self.reserve(max(20, ph) + 9)
        paragraph.drawOn(self.c, LEFT + 31, y - ph)
        self.y -= max(20, ph) + 9

    def note(self, text):
        paragraph = Paragraph(text, styles['body'])
        _, ph = paragraph.wrap(WIDTH - 24, 1000)
        height = ph + 20
        self.reserve(height + 10)
        self.c.setFillColor(PALE)
        self.c.roundRect(LEFT, self.y - height, WIDTH, height, 6, stroke=0, fill=1)
        paragraph.drawOn(self.c, LEFT + 12, self.y - 10 - ph)
        self.y -= height + 10

    def image(self, name, max_height, width=WIDTH, caption=None):
        file = ASSETS / f'{name}.png'
        im = PILImage.open(file)
        iw, ih = im.size
        scale = min(width / iw, max_height / ih)
        dw, dh = iw * scale, ih * scale
        self.reserve(dh + 12)
        x = LEFT + (WIDTH - dw) / 2
        self.c.drawImage(str(file), x, self.y - dh, dw, dh)
        self.c.setStrokeColor(LINE)
        self.c.setLineWidth(.5)
        self.c.rect(x, self.y - dh, dw, dh, stroke=1, fill=0)
        self.y -= dh + 8
        if caption:
            self.p(caption, 'small', after=10)

    def table(self, headers, rows, widths):
        data = [[Paragraph(escape(t), styles['tablehead']) for t in headers]]
        data += [[Paragraph(t, styles['cell']) for t in row] for row in rows]
        table = Table(data, colWidths=[WIDTH * v for v in widths], hAlign='LEFT')
        table.setStyle(TableStyle([
            ('BACKGROUND', (0, 0), (-1, 0), PALE),
            ('BOX', (0, 0), (-1, -1), .55, LINE),
            ('INNERGRID', (0, 0), (-1, -1), .4, LINE),
            ('VALIGN', (0, 0), (-1, -1), 'TOP'),
            ('LEFTPADDING', (0, 0), (-1, -1), 9),
            ('RIGHTPADDING', (0, 0), (-1, -1), 9),
            ('TOPPADDING', (0, 0), (-1, -1), 8),
            ('BOTTOMPADDING', (0, 0), (-1, -1), 8),
        ]))
        _, th = table.wrap(WIDTH, 1000)
        self.reserve(th + 12)
        table.drawOn(self.c, LEFT, self.y - th)
        self.y -= th + 12

    def finish(self):
        self.c.setStrokeColor(LINE)
        self.c.line(LEFT, 35, W - LEFT, 35)
        self.c.setFillColor(MUTED)
        self.c.setFont('Guide', 8)
        self.c.drawString(LEFT, 22, '操作说明 · 截图及数值仅作演示')
        self.c.drawRightString(W - LEFT, 22, f'{self.page} / 6')

    def save(self):
        self.finish()
        self.c.save()


g = Guide()
g.new('从第一次使用，到生成图纸', '适用：已有压缩弹簧图纸的识别、人工核对和成图。第一次建议只上传一张清晰图纸。')
g.note('<b>开始前：</b>从公司 ERP 登录后进入审图助手，或使用管理员提供的入口。若提示未登录，请返回 ERP 登录。生图服务由管理员配置，新手无需修改“高级选项”。')
g.p('<font color="#2452CB"><b>上传图纸 → 核对参数 → 确认要求 → 生成图纸 → 下载 PDF</b></font>', after=12)
g.image('workbench', 338, caption='工作台示例：左侧对照原图，右侧操作。“参数”和“生图参数包”是最常用的两个页签。')
g.step('1', '先看原图', '可用“适应窗口”、放大和左右90°旋转；有气泡时，点击编号可定位对应参数。')
g.step('2', '再看右侧', '在“参数”页逐项核对；核对完成后，切换“生图参数包”生成。')
g.note('<b>记住：</b>“识别完成”只表示提取结束；“已确认”表示你已核对；“生图版本”显示“已完成”，才表示新图纸生成结束。')

g.new('1  上传图纸，等待识别', '支持 PDF 和常见图片格式。先核对上传清单，再点击开始，选中文件并不会立即识别。')
g.image('upload-zone', 205, caption='上传区示例：先“选择文件”，看到文件列入清单后，再点击右下角“开始识别”。')
g.step('1', '选择文件', '点击“选择文件”，也可直接拖入图纸。批量时可以多选文件、选择文件夹或拖入文件夹。')
g.step('2', '核对清单', '确认文件没有选错或重复；不需要的点“移除”。每批最多50份；暂不支持压缩包。')
g.step('3', '开始并等待', '点击“开始识别”。从左侧“历史订单”查看进度，识别完成后点击对应订单打开审图。')
g.table(['看到的状态', '下一步'], [
    ['识别中 ＋ 百分比', '继续等待。批量任务可能排队，不需要反复上传。'],
    ['识别完成', '打开订单，进入人工核对。标题旁红点表示新结果尚未查看。'],
    ['识别失败', '查看原因，使用原订单的重试入口；仍失败时联系管理员。'],
], [.30, .70])
g.heading('出现“规格核对”怎么办？')
g.p('新上传的多规格图纸会<b>自动创建全部规格的审图记录，并在历史订单展开</b>。点击侧栏的规格直接审图；点来源标题可查看“规格核对”清单。每个规格仍需分别核对、确认和生图。旧订单可点“补建未创建规格”；已删除规格须点“重新创建审图”才恢复。')
g.p('多页 PDF 通常仍是一份订单；只有识别为多规格时才进入规格清单。相同文件可重复加入，每次都会新建订单，请避免误选。', 'small')

g.new('2  对照原图，确认参数', '进入右侧“参数”页。数值、公差、单位和端部状态都要与原图核对；不确定的先保留待确认。')
g.step('1', '看数值和公差', '优先核对材料、线径、三径、自由高度、总圈数、有效圈数、旋向和端部形式。圈数可为小数，例如10.5。')
g.image('parameter-detail', 259, width=340, caption='参数表示例：灰色“已确认”表示已经核对；可以操作的“确认”或“确认修改”表示仍需你处理。')
g.step('2', '有错就改，再确认', '直接改输入框或下拉选项，修改后重新点击该行“确认／确认修改”。系统自动保存；看到保存失败先重试。')
g.step('3', '批量确认要慎用', '逐项检查后再用“全部确认可确认项”。被跳过的缺值、冲突或失效项仍需单独处理。')
g.p('展开“高级参数”可补充支承圈数、节距、刚度和垂直度。直线度、永久变形限值、端圈数、弹体长度及受控直径缺值时隐藏；专项精度等级不显示。', 'small', after=5)
g.note('<b>两点特别注意：</b><br/>① 修改外径、内径或中径，会按当前线径联动另外两项；相关值需重新核对。<br/>② 图纸名称和图号可在摘要中直接修改。名称是图纸标题；图号是客户编号。')
g.heading('粗糙度没有识别到')
g.p('先检查原图。需要时可直接输入，或点击“采用 Ra 12.5／采用 Ra 6.3”，然后再确认；它们是<b>项目参考值，不是原图识别值</b>。不需要时选“不添加”。')

g.new('3  核对技术要求，缺值先问客户', '继续向下查看“技术要求”。确认的是当前正文；有原文或译文时，仍需人工核对内容是否准确。')
g.image('technical', 156, width=420, caption='技术要求卡片示例：检查类别和中文正文，确认无误后点击右侧“确认”。')
g.p('<b>普通要求：</b>检查正文、数值、单位、部位和工序顺序，再确认。<br/><b>表面处理：</b>公司类型下拉框辅助选名称，最终成图按已确认正文输出。<br/><b>翻译失败：</b>查看失败详情，可重新翻译或直接填写中文，之后再确认。', after=12)
g.heading('缺少参数或有疑问：导出“参数确认单”')
g.image('sheet-detail', 183, caption='A4确认单示例：参数与计算用文字列示，末尾标“确认”或RFI；优先一页，超长完整续页。')
g.p('“确认”表示我方已核对；RFI表示需客户澄清。设计校核结果展示数值、单位及确认／RFI标记，不附加计算或估算字样。客户重点回复RFI，无需逐项勾选已确认信息。', 'small', after=7)
g.step('1', '打开预览', '在“结构化尺寸数据”标题栏点击“预览确认单”；缺值也允许预览。')
g.step('2', '选择并打印', '选择打印项目，RFI说明随关联项目一起打印。Logo和字体就绪后查看预计页数，点击“打印／另存为PDF”，使用新版Chrome或Edge选择A4纵向、100%缩放。Logo失败可刷新重试。')
g.step('3', '收到反馈后回填', '请客户按RFI编号回复，可补充其他异议并填写姓名、日期。收到反馈后回原参数区修改和确认；预览及打印不会自动采用建议或确认参数。')

g.new('4  生成图纸，下载 PDF', '完成核对后，在“待处理”点击“去生图”，或切换“生图参数包”页。该页会列出还需补充、确认或处理的问题。')
g.step('1', '先看就绪提示', '有缺失、待确认或不可用参数时，返回对应项目处理；不要为了点亮按钮随意填数。')
g.image('generation-detail', 280, width=400, caption='生图设置示例：选择横版或竖版，核对署名，再点击“生成图纸”。')
g.step('2', '确认版式和姓名', '横版／竖版按需要选择。姓名首次带入登录姓名，之后沿用订单保存值；可修改但不能为空。设置随本次任务固定。')
g.step('3', '点击生成，等待完成', '点击一次“生成图纸”，在下方“生图版本”查看进度。不要因等待而连续点击创建。')
g.image('result', 100, width=420, caption='完成后的版本卡片示例；这里的任务状态仅用于说明操作。')
g.step('4', '打开并下载', '版本显示“已完成”后，点击“预览 PDF”，在打开的窗口中点击“下载 PDF”。有缩略图时也可以用“对比图纸”核对新旧图。')
g.note('<b>需要JSON参数包时，可在“AI对话”输入“导出参数包”。</b>图纸文件请等待生图完成后进入“预览 PDF”下载。')

g.new('遇到问题，按这里处理', '先看页面的具体提示。拿不准工程数值时，联系工程人员或客户确认；服务、登录或持续报错请联系管理员。')
g.table(['遇到的情况', '建议操作'], [
 ['“生成图纸”是灰色', '查看“生图参数包”中的缺失、待确认和参数不合理列表。补充并确认后再看；若提示服务不可用，联系管理员。'],
 ['显示“保存失败”', '保留当前页面，点击“重试保存”。不要先刷新或关闭，以免丢失尚未保存的输入。'],
 ['上传显示“结果待核对”', '先刷新历史订单，检查是否已经创建。已有订单就打开，不要直接再次提交同一项。'],
 ['参数有值，但没有气泡', '可能未找到可靠原图位置。先对照原图核对数值；可用“重新补定位”，必要时“调整标注”人工定位。'],
 ['生图失败／修改参数后要再出图', '失败时查看原因，修正后点击“重新生图”。修改参数后，也可回“生图参数包”点击“生成图纸”创建新版本；旧版本保持原样。'],
 ['PDF已生成，但对比图没显示', '先用“预览 PDF”查看或下载。需要缩略图时使用“重新生成预览”，不必立即重新生图。'],
 ], [.30, .70])
g.heading('可选功能，第一次可以先跳过')
g.p('<b>标准化：</b>需要按标准调整公差时再用。先核对通用精度等级，再生成、检查并应用建议；应用后重新核对受影响参数。标准化不是每次生图的必做步骤。')
g.p('<b>历史订单：</b>已完成的图纸可从左侧重新打开；红点仅表示新结果未查看。“批量管理”中的删除会删除服务器订单，操作前确认选择。')
g.note('<b>提交生成前，最后检查：</b><br/>名称／图号正确；关键数值、单位、公差已核对；需要输出的技术要求已确认；版式、姓名正确；当前修改已保存。')
g.p('补充说明：本手册介绍已有图纸的审图与成图，不把仅输入载荷、许用应力就自动反求整套弹簧尺寸作为已支持功能。规格代号用来区分多规格中的某一款。', 'small', after=7)
g.p('按2026年10月28日当前界面编写。截图使用演示数据，不构成生产参数；若公司部署版本不同，请向管理员确认入口和功能。', 'small')
g.save()
r = PdfReader(TARGET)
assert len(r.pages) == 6, len(r.pages)
all_text = '\n'.join(page.extract_text() or '' for page in r.pages)
for expected in ['开始识别', '预览确认单', '生成图纸', '下载 PDF', '客户', '多规格']:
    assert expected in all_text, expected
print(TARGET)
print('Pages:', len(r.pages), 'bytes:', TARGET.stat().st_size)

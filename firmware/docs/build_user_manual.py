from pathlib import Path

from docx import Document
from docx.enum.section import WD_SECTION
from docx.enum.style import WD_STYLE_TYPE
from docx.enum.table import WD_ALIGN_VERTICAL, WD_TABLE_ALIGNMENT
from docx.enum.text import WD_ALIGN_PARAGRAPH
from docx.oxml import OxmlElement
from docx.oxml.ns import qn
from docx.shared import Inches, Pt, RGBColor


OUT = Path(__file__).with_name("智能拐杖技术使用与调试手册.docx")

NAVY = "0B2545"
BLUE = "2E74B5"
DARK_BLUE = "1F4D78"
MUTED = "5B677A"
LIGHT_BLUE = "E8EEF5"
LIGHT_GRAY = "F2F4F7"
CALLOUT = "F4F6F9"
GOLD_FILL = "FFF7E1"
RED_FILL = "FDECEC"
GREEN = "1F7A4D"
YELLOW = "7A5A00"
RED = "9B1C1C"
TABLE_WIDTH = 9360
TABLE_INDENT = 120


def set_run_font(run, size=None, color=None, bold=None, italic=None, name="Microsoft YaHei"):
    run.font.name = name
    run._element.rPr.rFonts.set(qn("w:ascii"), name)
    run._element.rPr.rFonts.set(qn("w:hAnsi"), name)
    run._element.rPr.rFonts.set(qn("w:eastAsia"), name)
    if size is not None:
        run.font.size = Pt(size)
    if color:
        run.font.color.rgb = RGBColor.from_string(color)
    if bold is not None:
        run.bold = bold
    if italic is not None:
        run.italic = italic


def set_cell_shading(cell, fill):
    tc_pr = cell._tc.get_or_add_tcPr()
    shd = tc_pr.find(qn("w:shd"))
    if shd is None:
        shd = OxmlElement("w:shd")
        tc_pr.append(shd)
    shd.set(qn("w:fill"), fill)


def set_cell_margins(cell, top=80, start=120, bottom=80, end=120):
    tc_pr = cell._tc.get_or_add_tcPr()
    tc_mar = tc_pr.first_child_found_in("w:tcMar")
    if tc_mar is None:
        tc_mar = OxmlElement("w:tcMar")
        tc_pr.append(tc_mar)
    for side, value in (("top", top), ("start", start), ("bottom", bottom), ("end", end)):
        node = tc_mar.find(qn(f"w:{side}"))
        if node is None:
            node = OxmlElement(f"w:{side}")
            tc_mar.append(node)
        node.set(qn("w:w"), str(value))
        node.set(qn("w:type"), "dxa")


def set_cell_border(cell, color="D7DEE8", size="6"):
    tc_pr = cell._tc.get_or_add_tcPr()
    borders = tc_pr.first_child_found_in("w:tcBorders")
    if borders is None:
        borders = OxmlElement("w:tcBorders")
        tc_pr.append(borders)
    for edge in ("top", "left", "bottom", "right"):
        tag = qn(f"w:{edge}")
        node = borders.find(tag)
        if node is None:
            node = OxmlElement(f"w:{edge}")
            borders.append(node)
        node.set(qn("w:val"), "single")
        node.set(qn("w:sz"), size)
        node.set(qn("w:space"), "0")
        node.set(qn("w:color"), color)


def set_table_geometry(table, widths, indent=TABLE_INDENT):
    table.alignment = WD_TABLE_ALIGNMENT.LEFT
    table.autofit = False
    tbl = table._tbl
    tbl_pr = tbl.tblPr
    tbl_w = tbl_pr.first_child_found_in("w:tblW")
    if tbl_w is None:
        tbl_w = OxmlElement("w:tblW")
        tbl_pr.append(tbl_w)
    tbl_w.set(qn("w:w"), str(sum(widths)))
    tbl_w.set(qn("w:type"), "dxa")
    tbl_layout = tbl_pr.first_child_found_in("w:tblLayout")
    if tbl_layout is None:
        tbl_layout = OxmlElement("w:tblLayout")
        tbl_pr.append(tbl_layout)
    tbl_layout.set(qn("w:type"), "fixed")
    tbl_ind = tbl_pr.first_child_found_in("w:tblInd")
    if tbl_ind is None:
        tbl_ind = OxmlElement("w:tblInd")
        tbl_pr.append(tbl_ind)
    tbl_ind.set(qn("w:w"), str(indent))
    tbl_ind.set(qn("w:type"), "dxa")

    grid = tbl.tblGrid
    for child in list(grid):
        grid.remove(child)
    for width in widths:
        col = OxmlElement("w:gridCol")
        col.set(qn("w:w"), str(width))
        grid.append(col)

    for row in table.rows:
        for cell, width in zip(row.cells, widths):
            tc_pr = cell._tc.get_or_add_tcPr()
            tc_w = tc_pr.find(qn("w:tcW"))
            if tc_w is None:
                tc_w = OxmlElement("w:tcW")
                tc_pr.append(tc_w)
            tc_w.set(qn("w:w"), str(width))
            tc_w.set(qn("w:type"), "dxa")
            set_cell_margins(cell)
            set_cell_border(cell)
            cell.vertical_alignment = WD_ALIGN_VERTICAL.CENTER
        tr_pr = row._tr.get_or_add_trPr()
        cant_split = OxmlElement("w:cantSplit")
        tr_pr.append(cant_split)


def mark_header_row(row):
    tr_pr = row._tr.get_or_add_trPr()
    header = OxmlElement("w:tblHeader")
    header.set(qn("w:val"), "true")
    tr_pr.append(header)


def add_cell_text(cell, text, bold=False, color=None, size=9.5, align=None):
    cell.text = ""
    p = cell.paragraphs[0]
    p.paragraph_format.space_before = Pt(0)
    p.paragraph_format.space_after = Pt(0)
    p.paragraph_format.line_spacing = 1.15
    if align is not None:
        p.alignment = align
    r = p.add_run(text)
    set_run_font(r, size=size, color=color, bold=bold)


def add_table(doc, headers, rows, widths, header_fill=LIGHT_BLUE, font_size=9.5):
    table = doc.add_table(rows=1, cols=len(headers))
    set_table_geometry(table, widths)
    mark_header_row(table.rows[0])
    for cell, header in zip(table.rows[0].cells, headers):
        set_cell_shading(cell, header_fill)
        add_cell_text(cell, header, bold=True, color=NAVY, size=9.5,
                      align=WD_ALIGN_PARAGRAPH.CENTER)
    for row_values in rows:
        cells = table.add_row().cells
        for cell, value in zip(cells, row_values):
            add_cell_text(cell, str(value), size=font_size)
    for row_index, row in enumerate(table.rows[1:], start=1):
        if row_index % 2 == 0:
            for cell in row.cells:
                set_cell_shading(cell, "FAFBFC")
    add_spacer(doc, 5)
    return table


def set_paragraph_border(paragraph, color=BLUE, size="10", space="5"):
    p_pr = paragraph._p.get_or_add_pPr()
    borders = p_pr.find(qn("w:pBdr"))
    if borders is None:
        borders = OxmlElement("w:pBdr")
        p_pr.append(borders)
    bottom = OxmlElement("w:bottom")
    bottom.set(qn("w:val"), "single")
    bottom.set(qn("w:sz"), size)
    bottom.set(qn("w:space"), space)
    bottom.set(qn("w:color"), color)
    borders.append(bottom)


def add_spacer(doc, points=6):
    p = doc.add_paragraph()
    p.paragraph_format.space_before = Pt(0)
    p.paragraph_format.space_after = Pt(0)
    p.paragraph_format.line_spacing = Pt(points)
    return p


def add_body(doc, text, bold_prefix=None):
    p = doc.add_paragraph(style="Normal")
    if bold_prefix and text.startswith(bold_prefix):
        r = p.add_run(bold_prefix)
        set_run_font(r, bold=True)
        r = p.add_run(text[len(bold_prefix):])
        set_run_font(r)
    else:
        r = p.add_run(text)
        set_run_font(r)
    return p


def add_bullet(doc, text, level=0):
    p = doc.add_paragraph(style="List Bullet" if level == 0 else "List Bullet 2")
    p.paragraph_format.left_indent = Inches(0.375 + level * 0.25)
    p.paragraph_format.first_line_indent = Inches(-0.188)
    p.paragraph_format.space_after = Pt(4)
    p.paragraph_format.line_spacing = 1.25
    r = p.add_run(text)
    set_run_font(r)
    return p


def add_number(doc, text, level=0):
    p = doc.add_paragraph(style="List Number" if level == 0 else "List Number 2")
    p.paragraph_format.left_indent = Inches(0.375 + level * 0.25)
    p.paragraph_format.first_line_indent = Inches(-0.188)
    p.paragraph_format.space_after = Pt(4)
    p.paragraph_format.line_spacing = 1.25
    r = p.add_run(text)
    set_run_font(r)
    return p


def add_note_box(doc, title, text, fill=CALLOUT, title_color=NAVY):
    table = doc.add_table(rows=1, cols=1)
    set_table_geometry(table, [TABLE_WIDTH])
    cell = table.cell(0, 0)
    set_cell_shading(cell, fill)
    set_cell_border(cell, color="C9D3E1", size="8")
    p = cell.paragraphs[0]
    p.paragraph_format.space_before = Pt(1)
    p.paragraph_format.space_after = Pt(3)
    p.paragraph_format.line_spacing = 1.18
    r = p.add_run(title + "  ")
    set_run_font(r, size=10.5, color=title_color, bold=True)
    r = p.add_run(text)
    set_run_font(r, size=10.5)
    add_spacer(doc, 5)


def add_h1(doc, text):
    p = doc.add_paragraph(style="Heading 1")
    p.paragraph_format.keep_with_next = True
    r = p.add_run(text)
    set_run_font(r, size=16, color=BLUE, bold=True)
    return p


def add_h2(doc, text):
    p = doc.add_paragraph(style="Heading 2")
    p.paragraph_format.keep_with_next = True
    r = p.add_run(text)
    set_run_font(r, size=13, color=BLUE, bold=True)
    return p


def add_h3(doc, text):
    p = doc.add_paragraph(style="Heading 3")
    p.paragraph_format.keep_with_next = True
    r = p.add_run(text)
    set_run_font(r, size=12, color=DARK_BLUE, bold=True)
    return p


def add_page_number(paragraph):
    run = paragraph.add_run("第 ")
    set_run_font(run, size=9, color=MUTED)
    field = OxmlElement("w:fldSimple")
    field.set(qn("w:instr"), "PAGE")
    paragraph._p.append(field)
    run = paragraph.add_run(" 页")
    set_run_font(run, size=9, color=MUTED)


def set_document_styles(doc):
    section = doc.sections[0]
    section.page_width = Inches(8.5)
    section.page_height = Inches(11)
    section.top_margin = Inches(1)
    section.bottom_margin = Inches(1)
    section.left_margin = Inches(1)
    section.right_margin = Inches(1)
    section.header_distance = Inches(0.492)
    section.footer_distance = Inches(0.492)

    normal = doc.styles["Normal"]
    normal.font.name = "Microsoft YaHei"
    normal._element.rPr.rFonts.set(qn("w:eastAsia"), "Microsoft YaHei")
    normal.font.size = Pt(11)
    normal.paragraph_format.space_before = Pt(0)
    normal.paragraph_format.space_after = Pt(6)
    normal.paragraph_format.line_spacing = 1.25

    for name, size, color, before, after in [
        ("Heading 1", 16, BLUE, 18, 10),
        ("Heading 2", 13, BLUE, 14, 7),
        ("Heading 3", 12, DARK_BLUE, 10, 5),
    ]:
        style = doc.styles[name]
        style.font.name = "Microsoft YaHei"
        style._element.rPr.rFonts.set(qn("w:eastAsia"), "Microsoft YaHei")
        style.font.size = Pt(size)
        style.font.color.rgb = RGBColor.from_string(color)
        style.font.bold = True
        style.paragraph_format.space_before = Pt(before)
        style.paragraph_format.space_after = Pt(after)
        style.paragraph_format.line_spacing = 1.25

    for name in ("List Bullet", "List Bullet 2", "List Number", "List Number 2"):
        style = doc.styles[name]
        style.font.name = "Microsoft YaHei"
        style._element.rPr.rFonts.set(qn("w:eastAsia"), "Microsoft YaHei")
        style.font.size = Pt(11)
        style.paragraph_format.space_after = Pt(4)
        style.paragraph_format.line_spacing = 1.25


def set_header_footer(doc):
    for section in doc.sections:
        header = section.header
        p = header.paragraphs[0]
        p.alignment = WD_ALIGN_PARAGRAPH.LEFT
        p.paragraph_format.space_after = Pt(3)
        r = p.add_run("智能拐杖技术使用与调试手册")
        set_run_font(r, size=9, color=MUTED, bold=True)
        r = p.add_run("  |  当前固件功能基线")
        set_run_font(r, size=9, color=MUTED)
        set_paragraph_border(p, color="D7DEE8", size="5", space="3")

        footer = section.footer
        p = footer.paragraphs[0]
        p.alignment = WD_ALIGN_PARAGRAPH.RIGHT
        p.paragraph_format.space_before = Pt(3)
        r = p.add_run("ESP32-S3-CAM 智能拐杖  |  ")
        set_run_font(r, size=9, color=MUTED)
        add_page_number(p)


def add_cover(doc):
    add_spacer(doc, 86)
    p = doc.add_paragraph()
    p.alignment = WD_ALIGN_PARAGRAPH.CENTER
    p.paragraph_format.space_after = Pt(8)
    r = p.add_run("智能拐杖")
    set_run_font(r, size=30, color=NAVY, bold=True)

    p = doc.add_paragraph()
    p.alignment = WD_ALIGN_PARAGRAPH.CENTER
    p.paragraph_format.space_after = Pt(14)
    r = p.add_run("技术使用与调试手册")
    set_run_font(r, size=21, color=BLUE, bold=True)

    p = doc.add_paragraph()
    p.alignment = WD_ALIGN_PARAGRAPH.CENTER
    p.paragraph_format.space_after = Pt(24)
    r = p.add_run("基于 ESP32-S3-CAM、FreeRTOS、多传感器与 Wi-Fi 监控页面")
    set_run_font(r, size=12, color=MUTED)

    rule = doc.add_paragraph()
    rule.paragraph_format.space_after = Pt(16)
    set_paragraph_border(rule, color=BLUE, size="14", space="6")

    meta = [
        ("文档版本", "V1.0"),
        ("适用对象", "项目演示、功能调试、课程答辩与日常测试"),
        ("固件范围", "避障、SOS、跌倒检测、自动照明、GPS、摄像头、网页监控"),
        ("更新日期", "2026-07-27"),
    ]
    table = doc.add_table(rows=0, cols=2)
    set_table_geometry(table, [2100, 7260])
    for label, value in meta:
        cells = table.add_row().cells
        set_cell_shading(cells[0], LIGHT_BLUE)
        add_cell_text(cells[0], label, bold=True, color=NAVY, size=10)
        add_cell_text(cells[1], value, size=10)
    add_spacer(doc, 14)
    add_note_box(
        doc,
        "安全声明",
        "本系统为教学与原型验证设备。跌倒判断、避障与 GPS 仅用于辅助提示，不能替代人工看护、医疗设备或紧急救援服务。请勿通过真实摔倒方式测试。",
        fill=RED_FILL,
        title_color=RED,
    )
    doc.add_page_break()


def build_document():
    doc = Document()
    set_document_styles(doc)
    set_header_footer(doc)
    add_cover(doc)

    add_h1(doc, "1. 使用前快速了解")
    add_body(doc, "本手册以当前已经编译通过的 ESP32-S3-CAM 智能拐杖固件为准，帮助使用者完成上电、联网、网页监控、传感器验证、告警解除与常见故障排查。")
    add_h2(doc, "1.1 已实现功能")
    for item in [
        "HC-SR04 I2C 超声波测距与三级避障提醒。",
        "BH1750 环境照度检测与自动照明、手动开灯、手动关灯三种模式。",
        "JY901S IMU 姿态/加速度采集，以及组合规则式跌倒检测。",
        "ATGM336H GPS NMEA 解析、当前定位与本次上电期间的最后有效位置保存。",
        "实体 SOS 按键、网页 SOS、网页解除告警，以及蜂鸣器和照明 LED 的非阻塞提示节奏。",
        "OV2640 摄像头网页 MJPEG 视频流、单帧抓拍与状态 JSON 接口。",
        "FreeRTOS 双核多任务：传感器/决策/执行在 Core 1，网络/遥测在 Core 0。",
        "中文网页监控、固定高德静态地图与跳转高德详细位置链接。",
    ]:
        add_bullet(doc, item)
    add_h2(doc, "1.2 日常使用流程")
    for item in [
        "确认所有模块、天线和电源线连接牢固；尤其检查 GPS、IMU 与 I2C 共地。",
        "给 ESP32-S3-CAM 上电，打开串口监视器，确认启动日志无连续报错。",
        "使用手机或电脑接入设备热点，或让设备加入已配置的路由器/手机热点。",
        "浏览器打开设备 IP 地址，确认摄像头画面、传感器卡片和控制按钮出现。",
        "依次完成超声波、照明、SOS、GPS 与摄像头测试；跌倒测试只能使用受控方式。",
    ]:
        add_number(doc, item)
    add_note_box(doc, "推荐顺序", "先测试传感器和告警，再测试网络与网页；最后才进行跌倒算法的阈值校准。这样更容易定位问题。", fill=GOLD_FILL, title_color=YELLOW)

    add_h1(doc, "2. 硬件与接线说明")
    add_h2(doc, "2.1 关键接线表")
    add_table(
        doc,
        ["功能/模块", "ESP32-S3 GPIO", "信号方向或作用", "使用要点"],
        [
            ("I2C SDA（超声波、BH1750、OLED 共用）", "GPIO41", "双向数据线", "所有 I2C 模块共地；SDA/SCL 上拉应为 3.3 V。"),
            ("I2C SCL（超声波、BH1750、OLED 共用）", "GPIO42", "时钟线", "I2C 地址通常为：超声波 0x57、OLED 0x3C、BH1750 为 0x23 或 0x5C。"),
            ("JY901S TX", "GPIO39（ESP RX）", "IMU -> ESP32", "TX/RX 必须交叉连接；默认 9600 bps。"),
            ("JY901S RX", "GPIO38（ESP TX）", "ESP32 -> IMU", "若只读取 IMU 数据，可保留但建议仍接好。"),
            ("ATGM336H TX", "GPIO47（ESP RX）", "GPS -> ESP32", "GPS 数据进入 ESP32 的关键线路。"),
            ("ATGM336H RX", "GPIO21（ESP TX）", "ESP32 -> GPS", "用于 GPS 配置/命令通道。"),
            ("SOS 实体按键", "GPIO40", "按下为高电平", "按下触发；已锁存告警时再按一次解除。"),
            ("蜂鸣器控制", "GPIO1", "高电平响", "通过 MOS 驱动，不要把蜂鸣器负载直接接到普通 GPIO。"),
            ("照明/提示 LED", "GPIO14", "高电平亮", "同时承担夜间照明与部分告警闪烁提示。"),
        ],
        [2500, 1450, 2200, 3210],
        font_size=9,
    )
    add_h2(doc, "2.2 供电与安全检查")
    for item in [
        "GPS 模块推荐 VCC 接 ESP32 的 3V3，GND 接 ESP32 GND；GPS TX 接 GPIO47，GPS RX 接 GPIO21。",
        "ESP32-S3 的 GPIO 不耐受 5 V。任何模块的 TX、SDA 或 SCL 若输出 5 V，必须先经电平转换。",
        "摄像头启动和 Wi-Fi 发射会产生电流峰值。若摄像头黑屏、重启或 GPS 掉线，优先检查 5 V 电源余量与地线。",
        "板载相机占用 GPIO4、5、6、7、8、9、10、11、12、13、15、16、17、18 等固定引脚，禁止将外设接到这些相机引脚上。",
    ]:
        add_bullet(doc, item)

    add_h1(doc, "3. 编译、上传与串口监视")
    add_h2(doc, "3.1 PlatformIO 操作")
    for item in [
        "在 VS Code 中打开 SmartCane 工程文件夹，确认 PlatformIO 环境为 esp32-s3-cam。",
        "先点击 Build。首次构建会下载 ESP32 平台、工具链和 Arduino 框架；已下载完成的包会保存在本机缓存中，后续一般不会重复下载。",
        "看到 [SUCCESS] 后，连接开发板并在 PlatformIO 中选择正确的 COM 口，再点击 Upload。",
        "上传完成后，使用 115200 波特率打开串口监视器；如串口被占用，先关闭其他串口工具或已打开的监视器。",
    ]:
        add_number(doc, item)
    add_h2(doc, "3.2 启动日志的判断")
    add_table(
        doc,
        ["日志或现象", "表示什么", "下一步"],
        [
            ("[SmartCane] boot", "固件已启动。", "继续观察 I2C、GPS、相机和 FreeRTOS 日志。"),
            ("[BH1750] online / [Sonar] online / [OLED] online", "对应 I2C 模块已被识别。", "若显示 not found，检查地址、供电、SDA/SCL 和共地。"),
            ("[GPS] parser started at 9600 bps", "GPS 解析器已经以 9600 bps 启动。", "这不等于已定位，仍需观察 gps.valid 和卫星数。"),
            ("[Camera] PSRAM=...", "摄像头初始化流程已运行。", "camera=true 表示初始化成功；画面仍需由 /stream 实测。"),
            ("[FreeRTOS] Sensor/Decision/Actuator=Core1, Network/Telemetry=Core0", "多任务已启动。", "可继续进行网页和传感器联调。"),
            ("[SUCCESS] 后出现 PowerShell profile 脚本禁用提示", "Windows PowerShell 配置提示，与 PlatformIO 已成功构建无关。", "只要前面已显示 [SUCCESS]，无需因这条提示重新编译。"),
        ],
        [2600, 3000, 3760],
        font_size=9,
    )
    add_h2(doc, "3.3 无法上传时")
    add_body(doc, "若提示 Could not open COMx、port is busy 或拒绝访问，通常是串口正在被 PlatformIO Monitor、Arduino 串口监视器、其他调试工具占用，或 COM 号已变化。关闭占用程序，重新插拔数据线，在设备管理器确认当前 COM 号后再 Upload。")

    add_h1(doc, "4. 联网与网页监控教程")
    add_h2(doc, "4.1 两种联网方式")
    add_table(
        doc,
        ["方式", "连接方法", "网页地址", "适用场景"],
        [
            ("设备热点（AP）", "手机/电脑连接 SmartCane-Camera 热点；密码以 UserConfig.h 的 AP_PASSWORD 为准。", "通常为 http://192.168.4.1/", "离线演示、现场直连。设备热点本身不提供互联网。"),
            ("路由器/手机热点（STA）", "在 UserConfig.h 中配置 WIFI_SSID 与 WIFI_PASSWORD，设备上电后会尝试连接。", "串口、OLED 或状态行显示的实际 IP", "需要加载高德地图、手机和设备可同时联网的场景。"),
        ],
        [1500, 3100, 2050, 2710],
        font_size=9,
    )
    add_body(doc, "设备连接已配置路由器失败约 12 秒后，会自动降级为自身热点。网页卡片中的 IP 即当前应访问的地址。")
    add_h2(doc, "4.2 打开网页")
    for item in [
        "连接设备所在网络后，在浏览器输入网页 IP，例如设备热点模式的 http://192.168.4.1/。",
        "网页标题应为“智能拐杖监控”。初次进入时，摄像头视频流会自动尝试从 :81/stream 加载。",
        "上传新固件或修改网页后，如仍看到旧界面，请按 Ctrl+F5 强制刷新，或关闭浏览器标签后重新打开。",
    ]:
        add_number(doc, item)
    add_h2(doc, "4.3 网页区域与标识含义")
    add_table(
        doc,
        ["区域/标识", "含义", "正常或异常判断"],
        [
            ("摄像头画面", "来自端口 81 的 MJPEG 实时视频流。", "有连续画面即正常；黑屏或网络异常时见第 10 章排查。"),
            ("状态", "当前最高优先级告警状态。", "颜色：NORMAL 绿色；CAUTION/WARNING/DANGER 黄色；SOS/FALL 红色。"),
            ("距离 cm", "超声波当前有效距离。", "-- 表示暂未获得有效数据或传感器离线。"),
            ("光照 lx", "BH1750 环境照度。", "低于 20 lx 且为自动模式时，照明灯会点亮。"),
            ("GPS", "定位状态文字。", "定位、信号中断、搜索卫星、未定位分别表示不同 GNSS 状态。"),
            ("底部详情行", "IP、GPS 坐标/卫星、IMU 在线情况、照明状态与模式。", "IMU 显示离线时，系统不会把无效 IMU 数据当作跌倒。"),
            ("位置地图", "固定高德静态地图。", "绿色点为实时位置；黄色点为最后有效位置；地图不可拖动或缩放。"),
        ],
        [1900, 3100, 4360],
        font_size=9,
    )

    add_h1(doc, "5. 按钮、告警与照明说明")
    add_h2(doc, "5.1 网页按钮")
    add_table(
        doc,
        ["按钮", "作用", "使用后的表现"],
        [
            ("SOS 求助", "触发并锁存 SOS 告警。", "状态变为 SOS（红色），蜂鸣器和 LED 按 SOS 节奏闪烁；摄像头进入事件优先图传。"),
            ("解除告警", "解除 SOS 与 FALL 两种锁存告警，并重置跌倒检测器。", "若前方仍有近障，避障提醒会按当前距离重新出现。"),
            ("开灯", "设置手动常开照明。", "照明 LED 保持亮；网页中“开灯”按钮显示选中轮廓。"),
            ("关灯", "设置手动常关照明。", "会关闭普通夜间照明；但 SOS、FALL、DANGER 的可视告警闪烁不会被抑制。"),
            ("自动照明", "按 BH1750 照度自动控制照明。", "低于 20 lx 自动点亮；高于阈值则关闭。"),
        ],
        [1800, 3300, 4260],
        font_size=9,
    )
    add_h2(doc, "5.2 实体 SOS 按键")
    add_body(doc, "GPIO40 的实体按键使用“按下切换”逻辑，并经过约 30 ms 消抖。松开按键没有动作，长按不会连续触发。")
    for item in [
        "当前没有 SOS/FALL 锁存：按下一次，触发 SOS 并持续保持。",
        "当前已经有 SOS 或 FALL 锁存：再按下一次，请求解除锁存。",
        "解除后若障碍物仍处于警戒范围，系统会继续显示相应的避障状态；这不是解除失败。",
    ]:
        add_bullet(doc, item)
    add_h2(doc, "5.3 告警优先级、蜂鸣器与 LED")
    add_body(doc, "状态机始终只对最高优先级状态输出提示：SOS > FALL > DANGER（<30 cm）> WARNING（<50 cm）> CAUTION（<100 cm）> NORMAL。超声波恢复时使用 5 cm 回差，避免在临界距离反复跳变。")
    add_table(
        doc,
        ["状态", "网页颜色", "蜂鸣器节奏", "LED 行为"],
        [
            ("NORMAL", "绿色", "不响", "仅由手动/自动照明决定。"),
            ("CAUTION", "黄色", "约每 1.1 秒短响一次", "不作为避障闪烁输出。"),
            ("WARNING", "黄色", "约每 0.65 秒短响一次", "不作为避障闪烁输出。"),
            ("DANGER", "黄色", "约每 0.35 秒响一次", "约每 0.35 秒闪烁。"),
            ("FALL", "红色", "约每 0.8 秒响一次", "约每 0.8 秒闪烁，直到解除。"),
            ("SOS", "红色", "约每 0.4 秒响一次", "约每 0.4 秒闪烁，直到解除。"),
        ],
        [1300, 1300, 3000, 3760],
        font_size=9,
    )
    add_note_box(doc, "提示", "DANGER、FALL、SOS 时 LED 的闪烁优先级高于普通照明设置；因此在告警期间点击“关灯”不会让安全提示灯熄灭。", fill=GOLD_FILL, title_color=YELLOW)

    add_h1(doc, "6. 避障与跌倒检测原理")
    add_h2(doc, "6.1 避障判断")
    add_table(
        doc,
        ["距离范围", "状态", "解除条件", "用途"],
        [
            ("< 30 cm", "DANGER", "距离达到 35 cm 以上后才降级", "危险接近，蜂鸣和 LED 高频提示。"),
            ("30 cm 至 < 50 cm", "WARNING", "距离达到 55 cm 以上后才降级", "中等距离提醒。"),
            ("50 cm 至 < 100 cm", "CAUTION", "距离达到 105 cm 以上后才解除", "提前提醒使用者注意前方障碍。"),
            ("≥ 100 cm", "NORMAL", "无", "无近障告警。"),
        ],
        [1900, 1600, 2700, 3160],
        font_size=9,
    )
    add_body(doc, "若距离数据失效，系统会退出近障状态，避免使用过期距离持续告警。超声波只能辅助测距，易受目标材质、角度、软质物体与安装方向影响，应以实测为准。")
    add_h2(doc, "6.2 跌倒检测逻辑（演示初值）")
    add_body(doc, "跌倒检测不是单一阈值，而是按时间顺序组合 IMU 事件，以减少普通行走或拿起拐杖造成的误报。当前参数均在 UserConfig.h 中集中管理，必须按实际使用数据校准。")
    add_table(
        doc,
        ["阶段", "当前规则", "初始阈值"],
        [
            ("候选事件", "出现低重力或较大冲击时进入候选。", "低重力 ≤ 0.55 g；冲击 ≥ 2.20 g。"),
            ("冲击确认", "候选窗口中必须观察到冲击。", "候选窗口 1.5 s。"),
            ("倾倒与静止", "横滚角或俯仰角明显倾斜，且陀螺仪合速度较低。", "|roll| 或 |pitch| ≥ 55°；陀螺合速度 ≤ 35 °/s。"),
            ("持续确认", "倾倒并静止状态必须连续保持。", "保持 ≥ 800 ms。"),
            ("触发与冷却", "满足条件后锁存 FALL，短时间内不重复判定。", "冷却 3 s。"),
        ],
        [1900, 4200, 3260],
        font_size=9,
    )
    add_note_box(doc, "禁止事项", "不要让人真实摔倒来测试。推荐将拐杖固定在软垫上，以受控的小幅度动作模拟“冲击后倾斜静止”，并全程有人看护。", fill=RED_FILL, title_color=RED)
    add_h2(doc, "6.3 跌倒测试与调参建议")
    for item in [
        "先记录正常行走、正常放下拐杖、转身、跨台阶等 IMU 数据，确认不会误触发。",
        "在软垫与人工看护条件下，模拟冲击、倾斜和静止的顺序，观察 fall_latched 是否变为 true。",
        "若误报过多，可提高冲击阈值、增大倾角保持时间或降低静止阈值；每次只改一个参数。",
        "若漏报，可适当降低冲击阈值或缩短保持时间，但必须重新验证正常使用场景。",
    ]:
        add_number(doc, item)

    add_h1(doc, "7. GPS、地图与摄像头")
    add_h2(doc, "7.1 GPS 状态含义")
    add_table(
        doc,
        ["网页文字", "含义", "建议操作"],
        [
            ("定位", "当前 NMEA 数据有效，网页显示实时经纬度与卫星数。", "可查看高德静态地图和详细地图链接。"),
            ("信号中断", "当前失去有效定位，但本次上电期间曾成功定位。", "网页保留最后有效位置；检查天空视野和天线。"),
            ("搜索卫星", "GPS 有时间或卫星相关数据，但尚未形成有效定位。", "到室外开阔处静置，避免天线被金属或人体遮挡。"),
            ("未定位", "尚无可用定位数据。", "检查供电、共地、GPS TX -> GPIO47 与波特率。"),
        ],
        [1600, 4300, 3460],
        font_size=9,
    )
    add_body(doc, "GPS 的当前定位与最后有效位置都来自 WGS-84 坐标。最后有效位置只保存在本次上电的 RAM 中，断电或重启后会清空。首次冷启动、遮挡、天线方向和电源噪声都可能让定位时间变长或中断；不应把“曾经定位过”理解为始终具有可靠定位。")
    add_h2(doc, "7.2 高德地图显示")
    for item in [
        "网页底部为固定高德静态地图，不支持拖动、缩放或手势操作。",
        "实时定位时显示绿色标记；GPS 暂时失锁时，显示最后有效位置的黄色标记。",
        "为减少地图服务请求，网页以约 100 米粒度刷新静态地图；点击“在高德地图中打开”可查看完整精度位置。",
        "静态地图由手机/电脑浏览器直接从互联网加载。若手机仅连接 ESP32 独立热点且无法上网，地图无法加载是正常现象；避障、SOS、照明等本地功能不受影响。",
    ]:
        add_bullet(doc, item)
    add_h2(doc, "7.3 摄像头与抓拍")
    add_table(
        doc,
        ["地址", "用途", "说明"],
        [
            ("http://设备IP/", "中文监控主页", "自动加载 MJPEG 视频、状态与控制按钮。"),
            ("http://设备IP:81/stream", "MJPEG 视频流", "用于浏览器或上位机直接查看视频。"),
            ("http://设备IP/capture", "单帧 JPEG 抓拍", "返回一张当前相机图像；用于排查视频流问题。"),
            ("http://设备IP/api/status", "状态 JSON", "供网页和上位机读取距离、照度、IMU、GPS、告警与网络状态。"),
        ],
        [2600, 2500, 4260],
        font_size=9,
    )
    add_body(doc, "串口 JSON 中 camera=true 仅表示摄像头初始化成功；若 /capture 能返回图片但主页视频黑屏，优先检查浏览器缓存、:81 端口访问、手机网络和页面刷新。")

    add_h1(doc, "8. 传感器与功能测试步骤")
    add_h2(doc, "8.1 推荐测试顺序")
    add_table(
        doc,
        ["序号", "操作", "预期结果", "失败时优先检查"],
        [
            ("1", "上电并打开 115200 串口", "启动日志出现；已接 I2C 模块显示 online。", "供电、USB 数据线、串口 COM 号。"),
            ("2", "将障碍物在 1 m、50 cm、30 cm 附近移动", "CAUTION/WARNING/DANGER 随距离变化；危险区 LED 闪烁。", "超声波地址 0x57、I2C、安装方向。"),
            ("3", "遮住 BH1750，再恢复光照", "自动模式下低照度点灯，恢复光照后熄灭。", "BH1750 地址、阈值 20 lx、当前是否为自动模式。"),
            ("4", "网页依次点击开灯、关灯、自动照明", "照明模式改变，选中轮廓随之变化。", "网页是否刷新到新固件、/api/light 命令。"),
            ("5", "正常状态按实体 SOS 一次", "SOS 锁存，蜂鸣器和 LED 持续节奏提示。", "GPIO40、高电平按下、按键接线。"),
            ("6", "SOS/FALL 状态再按实体按键或网页解除告警", "锁存解除；若仍近障则返回避障状态。", "按键消抖、命令队列、距离读数。"),
            ("7", "室外开阔处静置 GPS", "gps.valid=true、经纬度、卫星数和地图出现。", "GPS 天线、3V3/GND、TX -> GPIO47、9600 bps。"),
            ("8", "打开主页与 /capture", "主页有视频；抓拍至少能获得单帧。", "电源、相机排线、浏览器和端口 81。"),
        ],
        [600, 3000, 3250, 2510],
        font_size=8.8,
    )
    add_h2(doc, "8.2 串口遥测与命令")
    add_body(doc, "串口波特率为 115200。系统会周期输出以 SC1 TEL 开头的 JSON，例如 alarm、distance_cm、lux、camera、imu、gps、last_fix 等字段。常用命令如下：")
    add_table(
        doc,
        ["串口输入", "作用"],
        [
            ("SC1 CMD SOS", "触发并锁存 SOS。"),
            ("SC1 CMD CANCEL", "解除 SOS/FALL 锁存，并重置跌倒检测器。"),
            ("SC1 CMD LIGHT ON", "手动常开照明。"),
            ("SC1 CMD LIGHT OFF", "手动常关普通照明。"),
            ("SC1 CMD LIGHT AUTO", "按 BH1750 照度自动照明。"),
        ],
        [3000, 6360],
        font_size=9.5,
    )

    add_h1(doc, "9. 常见故障排查")
    add_table(
        doc,
        ["现象", "可能原因", "处理方法"],
        [
            ("Build 提示缺少工具链/框架包", "PlatformIO 首次下载不完整或网络较慢。", "保持网络/代理可用，等待依赖下载；中断后已完整下载的包通常会被缓存。"),
            ("Upload 提示 COM 口忙或拒绝访问", "串口被监视器或其他程序占用。", "关闭 Monitor/Arduino 串口工具，确认当前 COM 口后重试。"),
            ("I2C devices: none 或模块 not found", "未供电、SDA/SCL 接反、地址不符、未共地。", "逐个模块接入；确认 GPIO41/42、3.3 V 上拉和对应地址。"),
            ("网页能打开但视频黑屏", "视频流端口 81 未连接、浏览器缓存或相机供电不稳。", "按 Ctrl+F5；直接打开 :81/stream 与 /capture；检查 5 V 供电。"),
            ("/capture 显示 capture failed", "相机未正确取到帧或供电不足。", "重新上电；检查相机排线、PSRAM/板型配置和电源。"),
            ("GPS 有 NMEA 但没有经纬度", "已收数据但尚未获得卫星定位。", "到开阔室外等待；天线朝上，远离摄像头/Wi-Fi 天线和金属遮挡。"),
            ("GPS 完全无 NMEA", "GPS TX、共地、供电或波特率不对。", "确认 GPS TX -> GPIO47、GND 共地、3V3；临时打开波特率诊断。"),
            ("高德地图空白", "浏览器没有互联网、地图 Key 配置或服务请求失败。", "确保手机/电脑能上网；不要公开地图 Key；检查本地 UserConfig.h 配置。"),
            ("网页开关灯无效", "浏览器仍为旧缓存，或命令没有发到新固件。", "Upload 后 Ctrl+F5；确认页面按钮和 light_mode 是否更新。"),
        ],
        [2100, 3380, 3880],
        font_size=8.8,
    )
    add_h2(doc, "9.1 GPS 波特率诊断")
    add_body(doc, "当前 GPS 默认波特率是 9600。若怀疑模块实际波特率不同，可将 UserConfig.h 中 GPS_BAUD_DIAGNOSTIC_ON_BOOT 临时改为 true，上传后重启。系统会依次测试常见波特率，并在串口打印校验正确的 NMEA 语句；确认后务必改回 false，以避免每次启动额外等待。")
    add_h2(doc, "9.2 需要保护的配置")
    for item in [
        "WIFI_SSID、WIFI_PASSWORD、AP_PASSWORD 和 AMAP_STATIC_MAP_KEY 都存放在 UserConfig.h。",
        "准备公开代码、截图、论文附录或提交仓库前，应替换真实网络凭据和地图 Key。",
        "网页静态地图需要将地图 Key 下发给浏览器；请只授予必要服务权限，并在高德控制台关注配额。",
    ]:
        add_bullet(doc, item)

    add_h1(doc, "10. 验收清单")
    add_body(doc, "以下清单可作为课堂演示、答辩或阶段验收记录。每项均建议记录日期、现场条件和异常备注。")
    add_table(
        doc,
        ["检查项", "通过标准", "结果（勾选/备注）"],
        [
            ("固件构建", "PlatformIO 显示 [SUCCESS]，无编译错误。", "□ 通过  □ 不通过  备注："),
            ("串口与启动", "115200 串口可读，I2C/IMU/GPS/相机启动信息合理。", "□ 通过  □ 不通过  备注："),
            ("超声波避障", "不同距离正确进入三级提示，危险区蜂鸣和 LED 闪烁。", "□ 通过  □ 不通过  备注："),
            ("自动与手动照明", "低照度自动亮；网页三种模式均可切换。", "□ 通过  □ 不通过  备注："),
            ("实体 SOS", "按一次锁存 SOS，再按一次解除。", "□ 通过  □ 不通过  备注："),
            ("网页 SOS/解除", "网页可锁存 SOS 并立即解除 SOS/FALL。", "□ 通过  □ 不通过  备注："),
            ("跌倒检测", "受控模拟符合规则时出现 FALL；正常操作不应频繁误报。", "□ 通过  □ 不通过  备注："),
            ("GPS 与地图", "室外可获得定位；失星时能显示最后有效位置。", "□ 通过  □ 不通过  备注："),
            ("摄像头", "主页 MJPEG 视频与 /capture 单帧均可工作。", "□ 通过  □ 不通过  备注："),
        ],
        [2200, 4200, 2960],
        font_size=9,
    )
    add_note_box(doc, "交付建议", "答辩演示前，先在室内完成避障、照明、SOS 与摄像头，再到室外完成 GPS 定位。将地图、视频和传感器结果分阶段展示，可靠性更高。", fill=LIGHT_BLUE, title_color=NAVY)

    doc.core_properties.title = "智能拐杖技术使用与调试手册"
    doc.core_properties.subject = "ESP32-S3-CAM 智能拐杖操作与调试"
    doc.core_properties.author = "SmartCane Project"
    doc.core_properties.comments = "基于当前项目固件功能生成；不包含网络或地图密钥。"
    doc.save(OUT)
    print(OUT)


if __name__ == "__main__":
    build_document()

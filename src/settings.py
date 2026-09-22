"""Native model settings, opened from the HUD menu. Saving requires a restart."""
from __future__ import annotations

import json
import threading
from pathlib import Path

import AppKit as A
import objc
from Foundation import NSObject, NSMakeRect

import builtin
import userconfig
import settings_config as config


class SettingsController(NSObject):
    @objc.python_method
    def build(self):
        self.path = userconfig.env_files()[0]
        self.original = config.read_document(self.path)
        values = userconfig.parse_env_file(self.path)
        self.file_values = values
        self.initial = {}
        self.fields = {}
        self.controls = []
        self.busy = False
        self.window = A.NSWindow.alloc().initWithContentRect_styleMask_backing_defer_(
            NSMakeRect(0, 0, 760, 600),
            A.NSWindowStyleMaskTitled | A.NSWindowStyleMaskClosable,
            A.NSBackingStoreBuffered, False)
        self.window.setAppearance_(A.NSAppearance.appearanceNamed_(A.NSAppearanceNameAqua))
        self.window.setTitle_("模型设置 · 保存后重启生效")
        self.window.setReleasedWhenClosed_(False)
        self.window.setDelegate_(self)
        view = self.window.contentView()
        self.label(view, "模型设置", 24, 548, 710, 30, 22)
        self.label(view, "保存不会切换当前服务；请退出并重新打开 jev-jarvis。", 24, 514, 710, 26)
        self.label(view, "编辑文件：" + str(self.path).replace(str(Path.home()), "~"),
                   24, 476, 710, 34, 12)
        self.tabs = A.NSTabView.alloc().initWithFrame_(NSMakeRect(16, 192, 728, 280))
        titles = ("判断 · Jev", "生成 · OpenAI 兼容", "生成 · Anthropic 兼容")
        for index, (prefix, title) in enumerate(zip(config.PREFIXES, titles)):
            item = A.NSTabViewItem.alloc().initWithIdentifier_(prefix)
            item.setLabel_(title)
            panel = A.NSView.alloc().initWithFrame_(NSMakeRect(0, 0, 690, 238))
            fields = {}
            for name, label, y in (("API_KEY", "密钥", 172), ("BASE_URL", "服务地址", 128), ("MODEL", "模型", 84)):
                self.label(panel, label, 14, y, 88, 26)
                cls = A.NSSecureTextField if name == "API_KEY" else A.NSComboBox if name == "MODEL" else A.NSTextField
                field = cls.alloc().initWithFrame_(NSMakeRect(104, y, 574, 26))
                default = "" if name == "API_KEY" else config.DEFAULTS[prefix][name == "MODEL"]
                value = values.get(f"{prefix}_{name}", default)
                if name == "API_KEY" and ("$(" in value or "`" in value):
                    value = ""  # Do not evaluate or rewrite shell/keychain expressions.
                    field.setToolTip_("此密钥由 shell 表达式提供；留空保留原行，输入新密钥才会替换。")
                field.setStringValue_(value)
                field.setFont_(A.NSFont.systemFontOfSize_(13))
                field.setDelegate_(self)
                field.setAccessibilityLabel_(title + " " + label)
                if name == "API_KEY":
                    field.setPlaceholderString_("由 shell 表达式提供：留空保留原行，输入新密钥才替换"
                                               if "$(" in values.get(f"{prefix}_{name}", "") or "`" in values.get(f"{prefix}_{name}", "")
                                               else "仅显示此文件中的密钥；不会复制环境变量中的密钥")
                if name == "MODEL":
                    field.setCompletes_(False)
                    field.setPlaceholderString_("获取模型列表后选择，或手动填写模型名称")
                panel.addSubview_(field)
                fields[name] = field
                self.initial[f"{prefix}_{name}"] = value
                self.controls.append(field)
            self.fields[prefix] = fields
            hint = ("Jev 地址不含 /v1；列表接口不可用时，可手填模型。" if prefix == "TYPESAFE"
                    else "可手填模型。Ollama 地址通常含 /v1，密钥可填 ollama。" if prefix == "OPENAI"
                    else "使用 Anthropic 消息接口，支持自定义兼容服务地址。")
            self.label(panel, hint, 14, 46, 666, 24, 12)
            for text, action, x in (("获取模型列表", "fetchModels:", 370), ("测试连接", "testConnection:", 532)):
                button = self.button(panel, text, action, x, 4, 150)
                button.setTag_(index)
                self.controls.append(button)
            item.setView_(panel)
            self.tabs.addTabViewItem_(item)
        view.addSubview_(self.tabs)
        self.label(view, self.current_source(), 24, 130, 710, 54, 12)
        self.label(view, "优先级：环境变量 > 用户 env > 项目 .env > 内置；两组生成密钥同时存在时 OpenAI 优先。\n清空此文件的密钥不屏蔽其他来源；切换服务需清除原来源中的优先密钥。", 24, 82, 710, 44, 12)
        self.status = self.label(view, "测试会发送固定问候语，不读取微信内容；可能产生少量服务费用。", 24, 36, 535, 42, 12)
        self.save_button = self.button(view, "保存配置", "saveSettings:", 602, 38, 134)
        self.controls.append(self.save_button)
        self.window.center()
        return self

    @objc.python_method
    def current_source(self):
        jev = userconfig.source_of("TYPESAFE_API_KEY", "JEV_API_KEY")
        judge = "本地判断" if jev == "none" else "自己的 Jev 密钥（" + jev + "）"
        oai = userconfig.provider("OPENAI")
        anth = userconfig.provider("ANTHROPIC")
        selected = oai if oai["key"] else anth
        gen = ("自己的密钥（" + selected["source"] + "）" if selected["key"]
               else "内置共享密钥" if builtin.API_KEY else "未配置")
        return ("本次启动 · 判断：" + judge + "\n生成：" + gen).replace(str(Path.home()), "~")

    @objc.python_method
    def label(self, view, text, x, y, w, h, size=13):
        field = A.NSTextField.wrappingLabelWithString_(text)
        field.setFrame_(NSMakeRect(x, y, w, h))
        field.setFont_(A.NSFont.systemFontOfSize_(size))
        view.addSubview_(field)
        return field

    @objc.python_method
    def button(self, view, title, action, x, y, width):
        button = A.NSButton.alloc().initWithFrame_(NSMakeRect(x, y, width, 32))
        button.setTitle_(title)
        button.setBezelStyle_(A.NSBezelStyleRounded)
        button.setTarget_(self)
        button.setAction_(action)
        view.addSubview_(button)
        return button

    @objc.python_method
    def show(self):
        self.window.makeKeyAndOrderFront_(None)
        A.NSApplication.sharedApplication().activateIgnoringOtherApps_(True)

    @objc.python_method
    def values(self, prefix):
        return {k: str(v.stringValue()) for k, v in self.fields[prefix].items()}

    @objc.python_method
    def changed(self):
        return {f"{p}_{k}": v for p in config.PREFIXES for k, v in self.values(p).items()
                if v != self.initial[f"{p}_{k}"]}

    def controlTextDidChange_(self, notification):
        field = notification.object()
        for fields in self.fields.values():
            if field in (fields["API_KEY"], fields["BASE_URL"]):
                combo = fields["MODEL"]
                current = combo.stringValue()
                combo.removeAllItems()
                combo.setStringValue_(current)
        self.status.setStringValue_("配置已修改，请重新测试；保存后重启生效。")

    def saveSettings_(self, sender):
        self.window.makeFirstResponder_(None)
        changes = self.changed()
        if not changes:
            self.status.setStringValue_("没有需要保存的修改。")
            return
        # Persist missing displayed defaults for edited services, but keep untouched key lines.
        for prefix in config.PREFIXES:
            if any(k.startswith(prefix + "_") for k in changes):
                changes.update({f"{prefix}_{k}": v for k, v in self.values(prefix).items()
                                if k != "API_KEY" and f"{prefix}_{k}" not in self.file_values})
        try:
            for prefix in config.PREFIXES:
                if any(k.startswith(prefix + "_") for k in changes):
                    vals = self.values(prefix)
                    if vals["API_KEY"] and (not vals["BASE_URL"].strip() or not vals["MODEL"].strip()):
                        raise ValueError("填写密钥后，请同时填写该服务的地址和模型。")
            for key, value in changes.items():
                if key.endswith("_BASE_URL") and value:
                    config.validate_endpoint(value)
            self.original = config.write_settings(self.path, self.original, changes)
        except ValueError as e:
            self.status.setStringValue_(str(e))
            return
        except OSError:
            self.status.setStringValue_("保存失败：请检查文件权限及可用磁盘空间。")
            return
        self.initial.update(changes)
        self.file_values.update(changes)
        self.status.setStringValue_("已保存。请退出并重新打开应用；当前会话继续使用启动时的配置。")

    def fetchModels_(self, sender):
        self.start_request(sender.tag(), True)

    def testConnection_(self, sender):
        self.start_request(sender.tag(), False)

    @objc.python_method
    def start_request(self, index, listing):
        if self.busy:
            return
        self.window.makeFirstResponder_(None)
        prefix = config.PREFIXES[index]
        values = self.values(prefix)
        try:
            config.validate_endpoint(values["BASE_URL"])
            if not values["API_KEY"]:
                raise ValueError("请填写密钥；Ollama 可填写 ollama。")
            if not listing and not values["MODEL"].strip():
                raise ValueError("请填写模型后再测试。")
            extra = None
            if not listing and prefix == "OPENAI":
                # Match generation's current extra-body setting, without changing it.
                raw = userconfig.get("OPENAI_EXTRA_BODY") or builtin.EXTRA_BODY
                extra = json.loads(raw) if raw else {}
                if not isinstance(extra, dict):
                    raise ValueError("OPENAI_EXTRA_BODY 必须是 JSON 对象。")
        except json.JSONDecodeError:
            self.status.setStringValue_("OPENAI_EXTRA_BODY 不是有效 JSON，请先修正该配置。")
            return
        except ValueError as e:
            self.status.setStringValue_(str(e))
            return
        if listing:
            combo = self.fields[prefix]["MODEL"]
            combo.removeAllItems()
            combo.setStringValue_(values["MODEL"])
        self.busy = True
        for control in self.controls:
            control.setEnabled_(False)
        self.status.setStringValue_("正在获取模型列表…" if listing else "正在测试所填服务与模型…")

        def work():
            result = {"index": index, "listing": listing}
            try:
                args = (prefix, values["BASE_URL"], values["API_KEY"])
                if listing:
                    result["models"] = config.list_models(*args)
                else:
                    config.test_connection(*args, values["MODEL"], extra)
            except Exception as e:
                result["error"] = config.error_message(e)
            self.performSelectorOnMainThread_withObject_waitUntilDone_("requestFinished:", result, False)
        threading.Thread(target=work, daemon=True).start()

    def requestFinished_(self, result):
        self.busy = False
        for control in self.controls:
            control.setEnabled_(True)
        if result.get("error"):
            self.status.setStringValue_(result["error"] + (" 模型仍可手填。" if result["listing"] else ""))
        elif result["listing"]:
            combo = self.fields[config.PREFIXES[result["index"]]]["MODEL"]
            current = combo.stringValue()
            combo.removeAllItems()
            combo.addItemsWithObjectValues_(result["models"])
            combo.setStringValue_(current)
            self.status.setStringValue_(f"已获取 {len(result['models'])} 个模型。请从下拉列表选择或手填，再测试连接。")
        else:
            self.status.setStringValue_("连接成功：所填服务与模型返回了有效结果。配置尚需保存并重启生效。")

    def windowShouldClose_(self, sender):
        if self.busy:
            self.status.setStringValue_("请求进行中，请等待结果后关闭。")
            return False
        if self.changed():
            alert = A.NSAlert.alloc().init()
            alert.setMessageText_("放弃尚未保存的配置？")
            alert.addButtonWithTitle_("继续编辑")
            alert.addButtonWithTitle_("放弃修改")
            return alert.runModal() == A.NSAlertSecondButtonReturn
        return True


if __name__ == "__main__":
    app = A.NSApplication.sharedApplication()
    app.setActivationPolicy_(A.NSApplicationActivationPolicyRegular)
    userconfig.load()
    controller = SettingsController.alloc().init().build()
    controller.show()
    app.run()

import asyncio, json
from playwright.async_api import async_playwright

BASE = "http://localhost:8090/index.html"

async def main():
    async with async_playwright() as p:
        browser = await p.chromium.launch()
        ctx = await browser.new_context()
        page = await ctx.new_page()
        errors = []
        page.on("pageerror", lambda e: errors.append(str(e)))
        page.on("console", lambda m: errors.append(m.text) if m.type == "error" else None)

        await page.goto(BASE, wait_until="networkidle")
        await page.wait_for_timeout(800)

        # 场景1：新增订阅源「量子位」
        await page.click('[data-nav="sources"]') if await page.query_selector('[data-nav="sources"]') else None
        # 找到订阅源导航（可能叫 settings/sources）
        navs = await page.eval_on_selector_all(".nav a, .sidebar a", "els=>els.map(e=>e.textContent.trim())")
        print("导航项:", navs)
        # 尝试直接调添加接口路径：打开订阅源页面
        await page.evaluate("()=>{ if(typeof aiOpen==='function'){} }")
        # 用 UI：点击导航里含「源」的项
        clicked = await page.evaluate("""()=>{
            const a=[...document.querySelectorAll('[data-nav]')].find(x=>/源|settings/.test(x.textContent+x.dataset.nav));
            if(a){a.click();return a.textContent.trim();} return null;}""")
        print("点击导航:", clicked)
        await page.wait_for_timeout(500)
        # 填写添加表单（折叠面板，直接用 JS 强制填写并提交）
        await page.evaluate("""()=>{
            const t=document.querySelector('[onclick*="ns_form"], .panel-toggle, #ns_toggle');
            // 展开折叠面板：找含「新增」的可点击标题
            if(t) t.click();
        }""")
        await page.wait_for_timeout(300)
        added = await page.evaluate("""()=>{
            const n=document.querySelector('#ns_name'); if(!n) return 'no-form';
            n.value='量子位';
            const u=document.querySelector('#ns_url'); if(u) u.value='https://www.qbitai.com';
            document.querySelector('#addSrc').click();
            return 'added';}""")
        await page.wait_for_timeout(500)
        print("添加量子位:", added)
        body_text = await page.inner_text("body")
        print("页面含量子位:", "量子位" in body_text)

        # 场景2：刷新按钮 → 仍有内容（量子位卡片 30 条）
        await page.evaluate("()=>{const a=[...document.querySelectorAll('[data-nav]')].find(x=>x.dataset.nav==='home'); a&&a.click();}")
        await page.wait_for_timeout(400)
        await page.evaluate("""()=>{
            const rf=[...document.querySelectorAll('button,[data-refresh]')].find(b=>/刷新/.test(b.textContent))||document.querySelector('[data-refresh]');
            if(rf) rf.click();}""")
        await page.wait_for_timeout(1200)
        cnt = await page.evaluate("()=>document.querySelectorAll('#grid .card').length")
        items = await page.evaluate("()=>{const q=[...document.querySelectorAll('#grid .card')].find(c=>c.textContent.includes('量子位'));return q?q.querySelectorAll('li,.item').length:-1;}")
        print("刷新后卡片数:", cnt, "量子位条目数:", items)

        # 场景3：搜索 → 右栏 AI 总结有内容
        await page.fill("#search", "量子位")
        await page.wait_for_timeout(1500)
        side = await page.inner_text("#aiSideBody") if await page.query_selector("#aiSideBody") else ""
        print("搜索总结非空:", bool(side.strip()), "| 主题概述:", "主题概述" in side or "围绕" in side)

        # 场景4：AI 助手对话
        await page.evaluate("()=>{const a=[...document.querySelectorAll('[data-nav]')].find(x=>x.dataset.nav==='assistant'); if(a)a.click(); if(typeof aiOpen==='function')aiOpen(true);}")
        await page.wait_for_timeout(600)
        await page.evaluate("""()=>{
            const i=document.querySelector('#aiInput'); i.value='量子位最近有哪些AI资讯';
            document.querySelector('#aiSend').click();}""")
        await page.wait_for_timeout(6000)
        await page.wait_for_timeout(4000)
        msg = await page.evaluate("()=>{const m=[...document.querySelectorAll('#aiBody .msg.bot')];return m.length?m[m.length-1].innerText.slice(0,200):'';}")
        print("AI 回复片段:", msg.replace("\n"," | ")[:180])

        # 场景5：深度总结按钮
        deep_cnt = await page.evaluate("()=>document.querySelectorAll('.item-deep').length")
        print("深度总结按钮数:", deep_cnt)
        if deep_cnt:
            await page.evaluate("()=>{const b=[...document.querySelectorAll('.item-deep')].find(x=>x.offsetParent); b&&b.click();}")
            await page.wait_for_timeout(1000)
            rep = await page.inner_text("#deepReply")
            print("深度总结:", rep[:150].replace("\n"," | "))

        # 场景6：资讯日报面板
        await page.evaluate("()=>{const a=[...document.querySelectorAll('[data-nav]')].find(x=>x.dataset.nav==='home'); a&&a.click();}")
        await page.wait_for_timeout(300)
        await page.evaluate("()=>{[...document.querySelectorAll('#nav a')].find(a=>a.dataset.nav==='daily').click()}")
        await page.wait_for_timeout(800)
        print("打开后导航高亮:", await page.evaluate("()=>document.querySelector('#nav a[data-nav=daily]').classList.contains('active')"))
        daily = await page.inner_text("#dailyBody")
        print("日报非空:", bool(daily.strip()) and "生成中" not in daily, "| 顶部速览非空:", await page.evaluate("()=>{const e=document.querySelector('#topFlash');return !!e && !e.hidden && e.innerText.includes('今日重点速览')}"), "| 日报不含重复速览:", "重点速览" not in daily, "| 含解读:", "解读" in daily, "| 含小结:", "一句话小结" in daily)
        await page.evaluate("document.querySelector('#dailyCollapse').click()")
        await page.wait_for_timeout(300)
        vis = await page.evaluate("()=>document.querySelector('#dailySide').classList.contains('collapsed')")
        print("可收缩:", vis, "| 收起后取消高亮:", await page.evaluate("()=>!document.querySelector('#nav a[data-nav=daily]').classList.contains('active')"))
        await page.evaluate("()=>{[...document.querySelectorAll('#nav a')].find(a=>a.dataset.nav==='daily').click()}")
        await page.wait_for_timeout(500)

        real_errs = [e for e in errors if "favicon" not in e]
        print("JS 错误:", real_errs[:5] if real_errs else "无")
        await browser.close()

asyncio.run(main())

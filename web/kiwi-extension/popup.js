/* Отдаёт cookies YouTube локальной качалке.
 *
 * Зачем расширение, а не закладка: SID и __Secure-* помечены httpOnly и в
 * document.cookie не видны в принципе. Прочитать их может только chrome.cookies,
 * то есть расширение. Читать базу браузера снаружи нельзя — каталог приложения
 * Android закрыт без root.
 *
 * Состав My Mix определяется идентичностью сессии в cookies: отдав их качалке,
 * получаем ровно ту станцию, что видно в этом браузере. */

const ENDPOINT = "http://127.0.0.1:8765/api/cookies";
const DOMAINS = ["youtube.com", "google.com"];   // SAPISID живёт на google.com

const msg = document.getElementById("msg");
const again = document.getElementById("again");

function show(title, detail, cls) {
  msg.className = cls || "";
  msg.innerHTML = "";
  const b = document.createElement("b");
  b.textContent = title;
  const s = document.createElement("span");
  s.className = "dim";
  s.textContent = detail || "";
  msg.appendChild(b);
  msg.appendChild(s);
}

function getAll(domain) {
  return new Promise((resolve) => {
    try {
      chrome.cookies.getAll({ domain }, (list) => resolve(list || []));
    } catch (e) {
      resolve([]);
    }
  });
}

async function collect() {
  const seen = new Set();
  const out = [];
  for (const d of DOMAINS) {
    for (const c of await getAll(d)) {
      const key = c.name + "\n" + c.domain + "\n" + c.path;
      if (seen.has(key)) continue;              // домены пересекаются
      seen.add(key);
      out.push({
        name: c.name, value: c.value, domain: c.domain, path: c.path,
        secure: !!c.secure, httpOnly: !!c.httpOnly,
        expires: c.expirationDate ? Math.floor(c.expirationDate) : 0,
      });
    }
  }
  return out;
}

async function send() {
  again.disabled = true;
  show("Собираю cookies…", "");
  let cookies;
  try {
    cookies = await collect();
  } catch (e) {
    show("Нет доступа к cookies", String(e), "err");
    again.disabled = false;
    return;
  }
  if (!cookies.length) {
    show("Cookies не найдены", "открой youtube.com и войди в аккаунт", "err");
    again.disabled = false;
    return;
  }

  show("Отправляю…", cookies.length + " cookies");
  try {
    const r = await fetch(ENDPOINT, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ cookies }),
    });
    const data = await r.json();
    if (data.ok) show("Готово ✓", data.msg || "", "ok");
    else show("Качалка отказала", data.msg || "", "err");
  } catch (e) {
    show("Качалка не отвечает", "запусти её: python main.py web", "err");
  }
  again.disabled = false;
}

again.addEventListener("click", send);
send();     // одного тапа по иконке достаточно

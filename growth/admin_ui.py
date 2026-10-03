"""Protected, same-origin BetSightly command center (no external runtime)."""

ADMIN_CSS = r"""
:root{
  color-scheme:dark;--bg:#07100e;--shell:#0a1512;--panel:#0e1c18;
  --panel-2:#12231e;--panel-3:#172b25;--line:#20372f;--line-2:#2b493e;
  --text:#f4f8f6;--text-2:#b6c7c0;--muted:#789087;--brand:#24d17e;
  --brand-2:#11a962;--brand-soft:rgba(36,209,126,.11);--blue:#61a8ff;
  --amber:#f3b95f;--red:#ff6b70;--purple:#ac8cff;--radius:16px;
  --shadow:0 20px 60px rgba(0,0,0,.22);--mono:"SFMono-Regular",Consolas,monospace;
}
*{box-sizing:border-box}html{scroll-behavior:smooth}
body{margin:0;background:radial-gradient(circle at 70% -20%,rgba(36,209,126,.12),transparent 38%),var(--bg);color:var(--text);font-family:Inter,ui-sans-serif,system-ui,-apple-system,"Segoe UI",sans-serif;line-height:1.45}
button,input,select{font:inherit}button{cursor:pointer}.hidden{display:none!important}
.login-shell{min-height:100vh;display:grid;place-items:center;padding:24px}
.login-card{width:min(420px,100%);padding:32px;background:linear-gradient(145deg,var(--panel-2),var(--panel));border:1px solid var(--line-2);border-radius:24px;box-shadow:var(--shadow)}
.brand{display:flex;align-items:center;gap:12px;font-weight:800;letter-spacing:-.03em;font-size:18px}.brand-mark{width:36px;height:36px;display:grid;place-items:center;border-radius:11px;background:linear-gradient(145deg,var(--brand),#7df4b6);color:#052014;font-size:20px;box-shadow:0 8px 24px rgba(36,209,126,.22)}
.login-card h1{font-size:30px;margin:30px 0 8px;letter-spacing:-.045em}.login-card p{color:var(--text-2)}
.field{width:100%;background:var(--panel-3);border:1px solid var(--line);color:var(--text);border-radius:12px;padding:12px 14px;outline:none}.field:focus{border-color:var(--brand);box-shadow:0 0 0 3px var(--brand-soft)}
.btn{border:1px solid var(--line-2);background:var(--panel-2);color:var(--text);border-radius:11px;min-height:40px;padding:9px 14px;font-weight:650}.btn:hover{border-color:#47705f;background:var(--panel-3)}.btn-primary{background:linear-gradient(135deg,var(--brand),var(--brand-2));border:0;color:#032116}.btn-ghost{background:transparent}.btn-danger{color:var(--red)}.btn:disabled{opacity:.45;cursor:not-allowed}.btn-wide{width:100%;margin-top:12px}
.error{color:var(--red);font-size:13px;min-height:20px}.muted{color:var(--muted)}
.shell{display:grid;grid-template-columns:248px minmax(0,1fr);min-height:100vh}
.sidebar{position:sticky;top:0;height:100vh;border-right:1px solid var(--line);background:rgba(7,16,14,.88);backdrop-filter:blur(20px);padding:24px 16px;display:flex;flex-direction:column;z-index:10}
.sidebar .brand{padding:0 8px 24px}.nav-label{font-size:10px;text-transform:uppercase;letter-spacing:.16em;color:var(--muted);font-weight:750;padding:14px 12px 7px}.nav{display:grid;gap:3px}.nav button{width:100%;border:0;background:transparent;color:var(--text-2);text-align:left;padding:10px 12px;border-radius:10px;font-weight:600;display:flex;align-items:center;gap:10px}.nav button:hover{color:var(--text);background:var(--panel)}.nav button.active{color:var(--text);background:var(--brand-soft);box-shadow:inset 3px 0 var(--brand)}.nav-icon{width:20px;text-align:center;color:var(--muted)}.nav button.active .nav-icon{color:var(--brand)}
.sidebar-foot{margin-top:auto;border-top:1px solid var(--line);padding-top:16px}.live{display:flex;align-items:center;gap:8px;color:var(--text-2);font-size:12px;padding:8px}.dot{width:7px;height:7px;border-radius:50%;background:var(--brand);box-shadow:0 0 0 5px var(--brand-soft)}
.workspace{min-width:0}.topbar{height:76px;display:flex;align-items:center;justify-content:space-between;gap:16px;padding:0 30px;border-bottom:1px solid var(--line);background:rgba(7,16,14,.72);backdrop-filter:blur(18px);position:sticky;top:0;z-index:9}.topbar-title strong{display:block;font-size:15px}.topbar-title span{font-size:12px;color:var(--muted)}.actions{display:flex;align-items:center;gap:8px;flex-wrap:wrap}
main{max-width:1520px;margin:0 auto;padding:28px 30px 64px}.page{display:none}.page.active{display:block}.page-head{display:flex;align-items:flex-end;justify-content:space-between;gap:18px;margin-bottom:24px}.eyebrow{font-size:11px;text-transform:uppercase;letter-spacing:.16em;color:var(--brand);font-weight:800;margin:0 0 7px}.page-head h1{font-size:30px;line-height:1.05;letter-spacing:-.045em;margin:0}.page-head p{color:var(--text-2);margin:8px 0 0;font-size:14px}.range{display:flex;align-items:center;gap:5px;min-width:0;max-width:100%;padding:5px;background:var(--panel);border:1px solid var(--line);border-radius:12px}.range button{border:0;background:transparent;color:var(--muted);border-radius:8px;padding:7px 11px;font-size:12px;font-weight:700}.range button.active{background:var(--panel-3);color:var(--text);box-shadow:0 1px 8px rgba(0,0,0,.2)}
.grid{display:grid;gap:14px}.kpis{grid-template-columns:repeat(6,minmax(130px,1fr))}.two{grid-template-columns:repeat(2,minmax(0,1fr))}.three{grid-template-columns:repeat(3,minmax(0,1fr))}.span-2{grid-column:span 2}.section{margin-top:24px}.section-head{display:flex;align-items:center;justify-content:space-between;gap:12px;margin-bottom:12px}.section-head h2{font-size:15px;margin:0;letter-spacing:-.015em}.section-head p{font-size:12px;color:var(--muted);margin:0}
.card{background:linear-gradient(145deg,rgba(18,35,30,.96),rgba(12,26,22,.96));border:1px solid var(--line);border-radius:var(--radius);padding:18px;box-shadow:0 1px 0 rgba(255,255,255,.02)}.card:hover{border-color:#2b493e}.card-flush{padding:0;overflow:hidden}.card-title{display:flex;align-items:center;justify-content:space-between;gap:10px;margin-bottom:14px}.card-title h3{font-size:13px;margin:0;color:var(--text-2)}
.card-flush>.card-title{padding:18px 18px 0}
.kpi{min-height:126px;position:relative;overflow:hidden}.kpi:after{content:"";position:absolute;width:80px;height:80px;border-radius:50%;right:-32px;top:-36px;background:var(--brand-soft)}.kpi-label{font-size:11px;color:var(--muted);text-transform:uppercase;letter-spacing:.08em;font-weight:750}.kpi-value{font:750 28px/1.1 var(--mono);letter-spacing:-.055em;margin:14px 0 8px}.delta{font:650 11px var(--mono);color:var(--muted)}.delta.up{color:var(--brand)}.delta.down{color:var(--red)}.kpi.hero{border-color:rgba(36,209,126,.4);background:linear-gradient(145deg,rgba(36,209,126,.16),var(--panel))}.kpi.hero .kpi-value{color:#75f0b1}
.health-grid{display:grid;grid-template-columns:1.2fr repeat(3,1fr);gap:0}.health-item{padding:16px;border-left:1px solid var(--line)}.health-item:first-child{border-left:0}.health-label{font-size:11px;color:var(--muted);text-transform:uppercase;letter-spacing:.07em}.health-value{font-size:18px;font-weight:750;margin-top:7px}.status{display:inline-flex;align-items:center;gap:6px;border-radius:99px;padding:4px 8px;font-size:10px;font-weight:800;text-transform:uppercase;letter-spacing:.06em}.ok{background:rgba(36,209,126,.12);color:var(--brand)}.warning{background:rgba(243,185,95,.12);color:var(--amber)}.bad{background:rgba(255,107,112,.12);color:var(--red)}.neutral{background:rgba(120,144,135,.13);color:var(--text-2)}
.funnel{display:grid;gap:7px}.funnel-row{display:grid;grid-template-columns:1fr auto 90px;gap:14px;align-items:center;padding:10px 12px;border-radius:10px;background:rgba(255,255,255,.018)}.funnel-row.worst{background:rgba(255,107,112,.07);outline:1px solid rgba(255,107,112,.18)}.funnel-name{font-size:13px;font-weight:650}.funnel-count{font:700 13px var(--mono)}.funnel-rate{text-align:right;font:600 11px var(--mono);color:var(--muted)}
.trend{height:170px;display:flex;align-items:flex-end;gap:5px;padding-top:14px}.trend-col{flex:1;min-width:5px;display:flex;flex-direction:column;justify-content:flex-end;height:100%;gap:5px}.trend-bar{width:100%;min-height:3px;border-radius:5px 5px 2px 2px;background:linear-gradient(180deg,var(--brand),rgba(36,209,126,.2))}.trend-col span{font:9px var(--mono);color:var(--muted);text-align:center;white-space:nowrap;overflow:hidden}.legend{display:flex;gap:16px;font-size:11px;color:var(--muted)}
.metric-list{display:grid;gap:11px}.metric-row{display:grid;grid-template-columns:minmax(100px,1fr) auto;gap:12px;align-items:center}.metric-row strong{font-size:12px}.metric-row span{font:650 12px var(--mono)}.mini-track{grid-column:1/-1;height:5px;background:rgba(255,255,255,.04);border-radius:4px;overflow:hidden}.mini-fill{height:100%;background:var(--brand);border-radius:4px}
.retention{display:grid;grid-template-columns:repeat(5,1fr);gap:8px}.retention-cell{padding:15px 10px;border-radius:12px;background:rgba(255,255,255,.025);text-align:center}.retention-cell strong{display:block;font:750 18px var(--mono)}.retention-cell span{font-size:10px;color:var(--muted);text-transform:uppercase;letter-spacing:.08em}
.alert{display:flex;gap:12px;padding:13px 0;border-bottom:1px solid var(--line)}.alert:last-child{border-bottom:0}.alert-icon{width:28px;height:28px;border-radius:8px;display:grid;place-items:center;background:rgba(243,185,95,.12);color:var(--amber);flex:0 0 auto}.alert strong{display:block;font-size:12px}.alert p{font-size:11px;color:var(--muted);margin:3px 0 0}
.table-wrap{overflow:auto}table{width:100%;border-collapse:collapse;min-width:620px}th,td{padding:12px 14px;border-bottom:1px solid var(--line);text-align:left;font-size:12px}th{font-size:10px;text-transform:uppercase;letter-spacing:.08em;color:var(--muted);font-weight:750;background:rgba(255,255,255,.012)}td.num{font-family:var(--mono)}tr:last-child td{border-bottom:0}tbody tr:hover{background:rgba(255,255,255,.018)}
.empty{padding:28px;text-align:center;color:var(--muted);font-size:12px}.note{border:1px solid rgba(243,185,95,.22);background:rgba(243,185,95,.06);border-radius:12px;padding:12px 14px;color:var(--text-2);font-size:12px}.row{display:flex;align-items:center;gap:9px}.wrap{flex-wrap:wrap}.switch{display:flex;align-items:center;justify-content:space-between;gap:14px;padding:11px 0;border-bottom:1px solid var(--line);font-size:12px}.switch:last-child{border-bottom:0}.switch input{accent-color:var(--brand)}
.tag{display:inline-flex;padding:3px 7px;border:1px solid var(--line-2);border-radius:99px;font:700 10px var(--mono)}.PUBLISHED,.FULL{color:var(--brand);border-color:rgba(36,209,126,.35)}.FAILED,.UNAVAILABLE{color:var(--red);border-color:rgba(255,107,112,.35)}.DRAFT{color:var(--amber)}.APPROVED,.SCHEDULED,.REBUILT_FULL{color:var(--blue)}.PARTIAL{color:var(--purple)}pre{white-space:pre-wrap;word-break:break-word;background:#08110f;border:1px solid var(--line);border-radius:12px;padding:15px;font:11px/1.6 var(--mono);max-height:420px;overflow:auto}
.mobile-toggle{display:none}
@media(max-width:1180px){.kpis{grid-template-columns:repeat(3,1fr)}.three{grid-template-columns:1fr 1fr}.health-grid{grid-template-columns:1fr 1fr}.health-item:nth-child(3){border-left:0;border-top:1px solid var(--line)}.health-item:nth-child(4){border-top:1px solid var(--line)}}
@media(max-width:800px){.shell{display:block}.sidebar{position:fixed;inset:0 auto 0 0;width:250px;transform:translateX(-105%);transition:.2s;box-shadow:var(--shadow)}.sidebar.open{transform:none}.mobile-toggle{display:inline-flex}.topbar{height:auto;min-height:66px;padding:12px 16px}.topbar .actions .desktop-action{display:none}main{padding:22px 16px 50px}.page-head{align-items:flex-start;flex-direction:column}.page-head>div{width:100%;min-width:0}.range{width:100%;overflow:auto}.kpis{grid-template-columns:1fr 1fr}.two,.three{grid-template-columns:1fr}.span-2{grid-column:auto}.health-grid{grid-template-columns:1fr}.health-item{border-left:0;border-top:1px solid var(--line)}.health-item:first-child{border-top:0}.retention{grid-template-columns:repeat(3,1fr)}}
@media(max-width:480px){.kpis{grid-template-columns:1fr 1fr}.kpi{min-height:112px;padding:14px}.kpi-value{font-size:23px}.funnel-row{grid-template-columns:1fr auto}.funnel-rate{grid-column:1/-1;text-align:left}.retention{grid-template-columns:1fr 1fr}.page-head h1{font-size:26px}}

/* command-center-ui-v2 */

:root{
  --bg:#090d0b;
  --shell:#0b100e;
  --panel:#101713;
  --panel-2:#131d18;
  --panel-3:#18241e;

  --line:rgba(236,247,241,.075);
  --line-2:rgba(236,247,241,.12);

  --text:#f5f8f6;
  --text-2:#bdc9c3;
  --muted:#7f8f87;

  --brand:#38e48d;
  --brand-2:#1fc876;
  --brand-soft:rgba(56,228,141,.105);

  --blue:#6faeff;
  --amber:#f4bd68;
  --red:#ff7478;
  --purple:#ae92ff;

  --radius:18px;
  --shadow:
    0 1px 1px rgba(0,0,0,.18),
    0 18px 50px rgba(0,0,0,.20);
}


html{
  background:var(--bg);
}

body{
  background:
    radial-gradient(circle at 78% -10%,rgba(56,228,141,.095),transparent 31rem),
    radial-gradient(circle at 8% 15%,rgba(111,174,255,.035),transparent 24rem),
    linear-gradient(180deg,#090d0b 0%,#080c0a 100%);
  font-feature-settings:"ss01","cv02","cv03";
  -webkit-font-smoothing:antialiased;
}


/* LOGIN */

.login-card{
  padding:38px;
  border-radius:28px;
  background:
    linear-gradient(145deg,rgba(20,31,26,.985),rgba(12,20,16,.985));
  border:1px solid rgba(255,255,255,.09);
  box-shadow:
    0 30px 100px rgba(0,0,0,.42),
    inset 0 1px rgba(255,255,255,.035);
}

.login-card h1{
  font-size:34px;
  margin-top:36px;
}

.brand-mark{
  width:40px;
  height:40px;
  border-radius:12px;
  border:1px solid rgba(255,255,255,.18);
  box-shadow:
    0 12px 32px rgba(56,228,141,.17),
    inset 0 1px rgba(255,255,255,.28);
}


/* APPLICATION SHELL */

.shell{
  grid-template-columns:270px minmax(0,1fr);
}

.sidebar{
  padding:22px 15px;
  background:
    linear-gradient(180deg,rgba(12,18,15,.985),rgba(8,13,11,.985));
  border-right:1px solid rgba(255,255,255,.065);
  box-shadow:12px 0 40px rgba(0,0,0,.12);
}

.sidebar .brand{
  padding:4px 10px 25px;
}

.nav-label{
  padding:18px 12px 8px;
  font-size:9px;
  letter-spacing:.18em;
}

.nav{
  gap:5px;
}

.nav button{
  min-height:45px;
  padding:7px 9px;
  border:1px solid transparent;
  border-radius:12px;
  gap:10px;
  font-size:13px;
  transition:
    background .16s ease,
    border-color .16s ease,
    color .16s ease,
    transform .16s ease;
}

.nav button:hover{
  background:rgba(255,255,255,.035);
  border-color:rgba(255,255,255,.045);
  transform:translateX(1px);
}

.nav button.active{
  background:
    linear-gradient(90deg,rgba(56,228,141,.13),rgba(56,228,141,.055));
  border-color:rgba(56,228,141,.13);
  box-shadow:none;
}

.nav-icon{
  width:31px;
  height:31px;
  display:grid;
  place-items:center;
  flex:0 0 auto;
  border:1px solid rgba(255,255,255,.055);
  background:rgba(255,255,255,.025);
  border-radius:9px;
  color:#95a59d;
  font-size:12px;
}

.nav button.active .nav-icon{
  color:var(--brand);
  border-color:rgba(56,228,141,.18);
  background:rgba(56,228,141,.09);
}

.sidebar-foot{
  padding-top:17px;
}

.live{
  border:1px solid rgba(255,255,255,.055);
  border-radius:11px;
  background:rgba(255,255,255,.02);
  padding:10px 11px;
}


/* TOP BAR */

.topbar{
  height:72px;
  padding:0 34px;
  border-bottom:1px solid rgba(255,255,255,.06);
  background:rgba(9,13,11,.82);
  backdrop-filter:blur(24px) saturate(130%);
  box-shadow:0 10px 32px rgba(0,0,0,.10);
}

.topbar-heading{
  display:flex;
  align-items:center;
  gap:9px;
}

.topbar-title strong{
  font-size:14px;
  font-weight:720;
}

.topbar-title>span{
  display:block;
  margin-top:2px;
}

.env-pill{
  display:inline-flex;
  align-items:center;
  gap:6px;
  padding:4px 8px;
  border:1px solid rgba(56,228,141,.16);
  border-radius:999px;
  background:rgba(56,228,141,.07);
  color:#8cefb8;
  font-size:9px;
  font-weight:800;
  letter-spacing:.08em;
  text-transform:uppercase;
}

.env-dot{
  width:6px;
  height:6px;
  border-radius:50%;
  background:var(--brand);
  box-shadow:0 0 0 4px rgba(56,228,141,.08);
}


/* CONTENT */

main{
  max-width:1480px;
  padding:34px 36px 80px;
}

.page{
  animation:admin-page-enter .18s ease both;
}

@keyframes admin-page-enter{
  from{
    opacity:0;
    transform:translateY(3px);
  }
  to{
    opacity:1;
    transform:none;
  }
}

.page-head{
  margin-bottom:27px;
  align-items:center;
}

.page-head h1{
  font-size:34px;
  letter-spacing:-.048em;
}

.page-head p{
  max-width:690px;
  color:#9eada6;
}

.eyebrow{
  margin-bottom:9px;
  font-size:10px;
}

.section{
  margin-top:31px;
}

.section-head{
  margin-bottom:14px;
}

.section-head h2{
  font-size:16px;
  font-weight:720;
}

.section-head p{
  font-size:12px;
}


/* RANGE CONTROL */

.range{
  gap:3px;
  padding:4px;
  border-radius:14px;
  background:rgba(255,255,255,.025);
  border-color:rgba(255,255,255,.07);
}

.range button{
  min-height:32px;
  padding:6px 11px;
  border-radius:9px;
}

.range button.active{
  background:#1a2620;
  color:#eff7f2;
  box-shadow:
    inset 0 0 0 1px rgba(255,255,255,.06),
    0 3px 10px rgba(0,0,0,.18);
}


/* BUTTONS */

.btn{
  min-height:39px;
  border-radius:10px;
  border-color:rgba(255,255,255,.085);
  background:#121a16;
  font-size:12px;
  transition:
    background .15s ease,
    border-color .15s ease,
    transform .15s ease;
}

.btn:hover{
  background:#18231d;
  border-color:rgba(255,255,255,.14);
  transform:translateY(-1px);
}

.btn-primary{
  background:linear-gradient(135deg,#42e997,#23c977);
  box-shadow:
    0 8px 24px rgba(35,201,119,.15),
    inset 0 1px rgba(255,255,255,.28);
}

.btn-primary:hover{
  background:linear-gradient(135deg,#4eeca0,#26d07c);
}


/* GRID SYSTEM */

.grid{
  gap:13px;
}

.kpis{
  grid-template-columns:repeat(auto-fit,minmax(180px,1fr));
}

.two{
  gap:16px;
}

.three{
  gap:16px;
}

.overview-funnel-grid{
  grid-template-columns:repeat(2,minmax(0,1fr));
  gap:16px;
}

.overview-insight-grid{
  grid-template-columns:repeat(2,minmax(0,1fr));
  gap:16px;
}

.overview-insight-grid .span-2{
  grid-column:1/-1;
}


/* CARDS */

.card{
  border-radius:18px;
  border:1px solid rgba(255,255,255,.07);
  background:
    linear-gradient(145deg,rgba(19,28,24,.93),rgba(13,21,17,.93));
  box-shadow:
    0 1px rgba(255,255,255,.018),
    0 10px 30px rgba(0,0,0,.095);
  transition:
    border-color .16s ease,
    background .16s ease,
    box-shadow .16s ease;
}

.card:hover{
  border-color:rgba(255,255,255,.105);
  background:
    linear-gradient(145deg,rgba(21,31,26,.96),rgba(14,22,18,.96));
}

.card-title{
  margin-bottom:17px;
}

.card-title h3{
  color:#d4ddd8;
  font-size:13px;
  font-weight:700;
}


/* KPI CARDS */

.kpi{
  min-height:132px;
  padding:19px;
}

.kpi:before{
  content:"";
  position:absolute;
  left:0;
  top:0;
  width:100%;
  height:2px;
  opacity:.5;
  background:
    linear-gradient(
      90deg,
      rgba(56,228,141,.7),
      rgba(56,228,141,0)
    );
}

.kpi:after{
  width:96px;
  height:96px;
  right:-46px;
  top:-49px;
  background:rgba(56,228,141,.055);
}

.kpi-label{
  font-size:10px;
  letter-spacing:.09em;
}

.kpi-value{
  margin:15px 0 10px;
  font-family:inherit;
  font-size:29px;
  font-weight:760;
  font-variant-numeric:tabular-nums;
  letter-spacing:-.045em;
}

.kpi.hero{
  border-color:rgba(56,228,141,.24);
  background:
    linear-gradient(145deg,rgba(56,228,141,.105),rgba(15,24,19,.98));
}

.kpi.hero .kpi-value{
  color:#7eefb0;
}

.delta{
  font-family:inherit;
  font-size:10px;
  font-weight:700;
}


/* HEALTH */

.health-grid{
  grid-template-columns:repeat(3,minmax(0,1fr));
  gap:1px;
  background:rgba(255,255,255,.065);
}

.health-item{
  min-height:119px;
  padding:18px;
  border:0;
  background:
    linear-gradient(145deg,#111a16,#0d1511);
}

.health-label{
  font-size:9px;
  letter-spacing:.09em;
}

.health-value{
  margin:9px 0 5px;
  font-size:19px;
}

.status{
  padding:5px 8px;
  font-size:9px;
  letter-spacing:.065em;
}


/* FUNNELS */

.funnel{
  gap:8px;
}

.funnel-row{
  padding:12px 13px;
  border:1px solid rgba(255,255,255,.045);
  border-radius:11px;
  background:rgba(255,255,255,.018);
}

.funnel-row.worst{
  background:rgba(255,116,120,.055);
  outline:none;
  border-color:rgba(255,116,120,.15);
}

.funnel-name{
  font-size:12px;
}

.funnel-count{
  min-width:35px;
  padding:4px 7px;
  border:1px solid rgba(255,255,255,.055);
  border-radius:8px;
  background:rgba(255,255,255,.025);
  text-align:center;
}

.funnel-rate{
  font-family:inherit;
  font-size:10px;
}


/* ALERTS */

#alerts{
  display:grid;
  gap:8px;
}

.alert{
  align-items:flex-start;
  padding:12px;
  border:1px solid rgba(255,255,255,.055);
  border-radius:11px;
  background:rgba(255,255,255,.018);
}

.alert:last-child{
  border-bottom:1px solid rgba(255,255,255,.055);
}

.alert-icon{
  width:30px;
  height:30px;
  border-radius:9px;
}

.alert-ok{
  border-color:rgba(56,228,141,.11);
  background:rgba(56,228,141,.035);
}

.alert-ok .alert-icon{
  color:var(--brand);
  background:rgba(56,228,141,.10);
}

.alert-warn .alert-icon{
  color:var(--amber);
  background:rgba(244,189,104,.10);
}

.alert strong{
  font-size:12px;
  line-height:1.35;
}

.alert p{
  margin-top:4px;
  line-height:1.45;
}


/* TREND */

.trend{
  height:205px;
  gap:7px;
  padding-top:20px;
}

.trend-bar{
  background:
    linear-gradient(
      180deg,
      rgba(56,228,141,.96),
      rgba(56,228,141,.18)
    );
}

.trend-col span{
  font-family:inherit;
  font-size:9px;
}


/* METRIC LISTS */

.metric-list{
  gap:13px;
}

.metric-row strong{
  color:#cbd5d0;
}

.metric-row span{
  font-family:inherit;
  font-variant-numeric:tabular-nums;
}

.mini-track{
  height:4px;
  background:rgba(255,255,255,.045);
}

.mini-fill{
  background:
    linear-gradient(
      90deg,
      #28ca79,
      #4be69a
    );
}


/* RETENTION */

.retention{
  gap:10px;
}

.retention-cell{
  min-height:95px;
  display:flex;
  flex-direction:column;
  justify-content:center;
  padding:16px 12px;
  border:1px solid rgba(255,255,255,.045);
  background:rgba(255,255,255,.018);
}

.retention-cell strong{
  font-family:inherit;
  font-size:20px;
}

.retention-cell span{
  margin-top:5px;
  font-size:9px;
}


/* TABLES */

.table-wrap{
  border-radius:inherit;
  scrollbar-width:thin;
  scrollbar-color:#33483e transparent;
}

table{
  min-width:680px;
}

th{
  position:sticky;
  top:0;
  z-index:1;
  padding:12px 15px;
  background:#111a16;
  color:#82938a;
  font-size:9px;
}

td{
  padding:13px 15px;
  color:#c4d0ca;
}

td.num{
  font-family:inherit;
  font-variant-numeric:tabular-nums;
}

tbody tr{
  transition:background .12s ease;
}

tbody tr:hover{
  background:rgba(56,228,141,.026);
}


/* FIELDS */

.field{
  min-height:42px;
  border-radius:10px;
  border-color:rgba(255,255,255,.075);
  background:#131d18;
}

.field:hover{
  border-color:rgba(255,255,255,.12);
}

.field:focus{
  border-color:rgba(56,228,141,.52);
  box-shadow:0 0 0 3px rgba(56,228,141,.08);
}


/* NOTES */

.note{
  margin:14px 34px 0;
  border-color:rgba(244,189,104,.16);
  background:rgba(244,189,104,.045);
}


/* SCROLLBAR */

*::-webkit-scrollbar{
  width:9px;
  height:9px;
}

*::-webkit-scrollbar-track{
  background:transparent;
}

*::-webkit-scrollbar-thumb{
  border:2px solid transparent;
  border-radius:999px;
  background:#30443a;
  background-clip:padding-box;
}


/* RESPONSIVE */

@media(max-width:1200px){

  .shell{
    grid-template-columns:242px minmax(0,1fr);
  }

  main{
    padding-left:26px;
    padding-right:26px;
  }

  .health-grid{
    grid-template-columns:repeat(2,minmax(0,1fr));
  }

  .kpis{
    grid-template-columns:repeat(3,minmax(0,1fr));
  }
}

@media(max-width:900px){

  .overview-funnel-grid,
  .overview-insight-grid{
    grid-template-columns:1fr;
  }

  .overview-insight-grid .span-2{
    grid-column:auto;
  }

  .kpis{
    grid-template-columns:repeat(2,minmax(0,1fr));
  }
}

@media(max-width:800px){

  .sidebar{
    width:274px;
  }

  .topbar{
    padding-left:16px;
    padding-right:16px;
  }

  main{
    padding:25px 16px 58px;
  }

  .note{
    margin:12px 16px 0;
  }

  .page-head{
    align-items:flex-start;
  }

  .page-head h1{
    font-size:30px;
  }

  .health-grid{
    grid-template-columns:1fr;
  }
}

@media(max-width:520px){

  .kpis{
    grid-template-columns:repeat(2,minmax(0,1fr));
    gap:9px;
  }

  .kpi{
    min-height:115px;
    padding:14px;
  }

  .kpi-value{
    font-size:23px;
  }

  .page-head h1{
    font-size:27px;
  }

  .section{
    margin-top:26px;
  }

  .funnel-row{
    grid-template-columns:1fr auto;
  }

  .retention{
    grid-template-columns:repeat(2,minmax(0,1fr));
  }

  .topbar-heading .env-pill{
    display:none;
  }
}


/* command-center-final-polish */

/* Sidebar must never hide lower navigation/settings on short screens. */
.sidebar{
  height:100dvh;
  min-height:0;
  overflow-y:auto;
  overflow-x:hidden;
  overscroll-behavior:contain;
  scrollbar-gutter:stable;
}

.sidebar-foot{
  margin-top:22px;
  padding-bottom:8px;
  flex:0 0 auto;
}

.sidebar .nav{
  flex:0 0 auto;
}

/* Quieter comparison copy. */
.delta{
  opacity:.82;
}

/* Make loading visible instead of leaving an apparently frozen dashboard. */
.dashboard-loading #period{
  color:var(--brand);
}

.dashboard-loading #period:before{
  content:"";
  display:inline-block;
  width:7px;
  height:7px;
  margin-right:8px;
  border-radius:50%;
  background:var(--brand);
  box-shadow:0 0 0 4px rgba(56,228,141,.09);
  animation:admin-loading-pulse .8s ease-in-out infinite alternate;
}

@keyframes admin-loading-pulse{
  from{opacity:.35;transform:scale(.85)}
  to{opacity:1;transform:scale(1.05)}
}

/* Compact sidebar when laptop height is limited. */
@media(min-width:801px) and (max-height:820px){
  .sidebar{
    padding-top:14px;
    padding-bottom:12px;
  }

  .sidebar .brand{
    padding-bottom:13px;
  }

  .nav-label{
    padding-top:8px;
    padding-bottom:4px;
  }

  .nav{
    gap:2px;
  }

  .nav button{
    min-height:38px;
    padding-top:4px;
    padding-bottom:4px;
  }

  .nav-icon{
    width:27px;
    height:27px;
  }

  .sidebar-foot{
    margin-top:12px;
    padding-top:10px;
  }

  .live{
    padding:7px 9px;
  }

  .sidebar-foot .btn{
    min-height:36px;
  }
}

/* Very short laptop screens still remain completely navigable. */
@media(min-width:801px) and (max-height:690px){
  .nav button{
    min-height:34px;
    font-size:12px;
  }

  .nav-icon{
    width:24px;
    height:24px;
  }

  .nav-label{
    font-size:8px;
  }
}

/* Mobile should become a true single-column dashboard. */
@media(max-width:560px){
  .kpis{
    grid-template-columns:1fr;
  }

  .retention{
    grid-template-columns:1fr;
  }

  .kpi{
    min-height:auto;
  }

  .health-item{
    min-height:auto;
  }
}

"""

ADMIN_JS = r"""
const API='/api/growth', $=id=>document.getElementById(id);let SETTINGS={},DASH=null;
const esc=s=>String(s??'').replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;').replace(/"/g,'&quot;');
const pct=v=>v==null?'—':(Number(v)*100).toFixed(Number(v)<.1?1:0)+'%';
const num=v=>Number(v||0).toLocaleString();
const maybeNum=v=>v==null?'—':num(v);
const when=v=>{if(!v)return'Awaiting today’s run';const d=new Date(v);return Number.isNaN(d.valueOf())?String(v):d.toLocaleString(undefined,{dateStyle:'medium',timeStyle:'short'})};
const isToday=v=>{if(!v)return false;const d=new Date(v),n=new Date();return !Number.isNaN(d.valueOf())&&d.getFullYear()===n.getFullYear()&&d.getMonth()===n.getMonth()&&d.getDate()===n.getDate()};
async function api(path,opts={}){const r=await fetch(API+path,{credentials:'same-origin',headers:{'Content-Type':'application/json'},...opts});if(r.status===401){show('login');throw Error('Session expired');}const b=await r.json().catch(()=>({}));if(!r.ok)throw Error(b.detail||b.message||'Request failed');return b}
function show(which){$('login').classList.toggle('hidden',which!=='login');$('app').classList.toggle('hidden',which==='login')}
function nav(name,button){document.querySelectorAll('.page').forEach(p=>p.classList.toggle('active',p.id==='page-'+name));document.querySelectorAll('.nav button').forEach(b=>b.classList.remove('active'));if(button)button.classList.add('active');$('side').classList.remove('open');if(name==='content')loadContent();if(name==='publishing')loadPubs();if(name==='settings')loadSettings();if(name==='referrals')loadRefs()}
async function login(){try{await api('/admin/login',{method:'POST',body:JSON.stringify({password:$('pw').value})});$('pw').value='';show('app');boot()}catch(e){$('loginErr').textContent=e.message}}
async function logout(){try{await api('/admin/logout',{method:'POST'})}catch(e){}show('login')}
function delta(metric){const v=DASH?.vs_previous?.changes?.[metric];if(v==null)return'<span class="delta">No prior baseline</span>';if(Number(v)===0)return'<span class="delta">— No change vs prior</span>';return`<span class="delta ${v>0?'up':'down'}">${v>0?'↗':'↘'} ${Math.abs(v*100).toFixed(0)}% vs prior</span>`}
function kpi(label,value,metric,hero=false,format='num'){return`<article class="card kpi ${hero?'hero':''}"><div class="kpi-label">${esc(label)}</div><div class="kpi-value">${format==='pct'?pct(value):typeof value==='string'?esc(value):num(value)}</div>${delta(metric)}</article>`}
function sourceLine(meta){if(!meta)return'';const age=meta.freshness_seconds==null?'age unknown':meta.freshness_seconds<60?'just now':Math.round(meta.freshness_seconds/60)+'m old';return`<span class="status ${meta.status==='fresh'?'ok':meta.status==='stale'?'warning':'bad'}">${esc(meta.source)} · ${esc(meta.status)} · ${age}</span>`}
function empty(text='No data in this period yet.'){return`<div class="empty">${esc(text)}</div>`}
function table(headers,rows){return rows.length?`<div class="table-wrap"><table><thead><tr>${headers.map(h=>`<th>${esc(h)}</th>`).join('')}</tr></thead><tbody>${rows.join('')}</tbody></table></div>`:empty()}
function bars(rows,value='visitors'){if(!rows?.length)return empty();const max=Math.max(1,...rows.map(r=>r[value]||0));return`<div class="metric-list">${rows.slice(0,8).map(r=>`<div class="metric-row"><strong>${esc(r.key)}</strong><span>${num(r[value])}</span><div class="mini-track"><div class="mini-fill" style="width:${Math.max(2,(r[value]||0)/max*100)}%"></div></div></div>`).join('')}</div>`}
function renderTrend(rows){if(!rows?.length)return empty();const max=Math.max(1,...rows.map(r=>r.visitors));return`<div class="trend">${rows.map(r=>`<div class="trend-col" title="${esc(r.date)} · ${r.visitors} visitors"><div class="trend-bar" style="height:${Math.max(3,r.visitors/max*100)}%"></div><span>${esc(r.date.slice(5))}</span></div>`).join('')}</div>`}
function funnel(rows){if(!rows?.length)return empty();let worst=-1;rows.forEach((x,i)=>{if(i&&x.dropoff>worst)worst=x.dropoff});return rows.map((x,i)=>`<div class="funnel-row ${i&&x.dropoff===worst&&x.dropoff>.2?'worst':''}"><span class="funnel-name">${esc(x.label)}</span><span class="funnel-count">${num(x.count)}</span><span class="funnel-rate">${i?(x.conversion==null?'No eligible prior step':`${pct(x.conversion)} continue · ${pct(x.dropoff)} drop`):'Entry'}</span></div>`).join('')}
function renderOverview(){const s=DASH.summary,t=s.totals,b=s.booking,sb=s.sportybet||{},runs=s.operations?.runs||[],last=runs[0],country=s.by_country?.[0]?.key||'—',mobile=s.by_device?.find(x=>String(x.key).toLowerCase()==='mobile'),mobileShare=t.visitors?((mobile?.visitors||0)/t.visitors):null,runIsToday=isToday(last?.finished_at),runSucceeded=['success','complete'].includes(String(last?.status||'').toLowerCase());$('audienceKpis').innerHTML=[kpi('Visitors',t.visitors,'visitors'),kpi('Returning users',t.returning_visitors,'returning_visitors',true),kpi('Sessions',t.sessions,'sessions'),kpi('Primary country',country,'country'),kpi('Mobile share',mobileShare,'mobile',false,'pct')].join('');$('engagementKpis').innerHTML=[kpi('Prediction users',t.prediction_viewers,'prediction_viewers'),kpi('Builder users',t.builder_users,'builder_users'),kpi('Rollover users',t.rollover_users,'rollover_users'),kpi('Valid-code viewers',t.valid_code_viewers,'valid_code_viewers'),kpi('Unique code copiers',t.unique_code_copiers,'unique_code_copiers',true),kpi('SportyBet openers',t.sportybet_openers,'sportybet_openers')].join('');$('systemKpis').innerHTML=[kpi('Automated bookings',b.attempts,'attempts'),kpi('Successful bookings',(b.full||0)+(b.rebuilt||0)+(b.partial||0),'full',true),kpi('Validation success',b.validation_success_rate,'validation_success_rate',false,'pct'),kpi('No-code rate',b.no_code_rate,'no_code_rate',false,'pct')].join('');
 const unique=sb.unique_indexed_fixtures??sb.fixtures??0,declared=sb.declared_total??null;const complete=sb.is_complete===true&&sb.error==null;const providerTotal=declared==null?'—':num(declared);$('health').innerHTML=`<div class="health-item"><div class="health-label">Today’s prediction run</div><div class="health-value"><span class="status ${!last?'neutral':!runIsToday?'warning':runSucceeded?'ok':'warning'}">${esc(!last?'No run':!runIsToday?'Stale':runSucceeded?'Complete':last.status)}</span></div><div class="muted">${esc(!last?'Awaiting today run':runIsToday?when(last.finished_at):`Last run ${when(last.finished_at)}`)}</div></div><div class="health-item"><div class="health-label">SportyBet unique fixtures</div><div class="health-value">${num(unique)}</div><div class="muted">Provider total estimate: ${providerTotal}</div><span class="status ${complete?'ok':'bad'}">${complete?'Complete':'Incomplete'}</span></div><div class="health-item"><div class="health-label">System booking health</div><div class="health-value">${pct(b.success_rate)}</div><div class="muted">${num(b.attempts)} automated attempts</div></div><div class="health-item"><div class="health-label">Settlement / jobs</div><div class="health-value">${last?.failed?.length?'<span class="status bad">Attention</span>':'<span class="status ok">Healthy</span>'}</div><div class="muted">${last?.failed?.length?esc(last.failed.join(', ')):'No reported failures'}</div></div>`;
 const integrity=s.analytics_integrity||{},integrityBad=integrity.status==='error';$('health').insertAdjacentHTML('beforeend',`<div class="health-item"><div class="health-label">Analytics ingestion</div><div class="health-value"><span class="status ${s.analytics_provider?.status==='fresh'?'ok':'warning'}">${s.analytics_provider?.status==='fresh'?'Healthy':'Degraded'}</span></div><div class="muted">Provider freshness only.</div></div><div class="health-item"><div class="health-label">Analytics integrity</div><div class="health-value"><span class="status ${integrity.status==='healthy'?'ok':integrityBad?'bad':'warning'}">${esc(integrity.status||'Unknown')}</span></div><div class="muted">${num((integrity.issues||[]).length)} consistency issue(s).</div></div>`);$('predictionFunnel').innerHTML=funnel(s.funnels?.prediction);$('builderFunnel').innerHTML=funnel(s.funnels?.builder);$('rolloverFunnel').innerHTML=funnel(s.funnels?.rollover);$('trend').innerHTML=renderTrend(s.daily);$('topPages').innerHTML=bars(s.by_path);$('sourcesMini').innerHTML=bars(s.by_source);
 const alerts=[];if(last&&!runIsToday)alerts.push(['Prediction run stale',`Latest recorded run finished ${when(last.finished_at)}.`]);if(integrity.status==='error')alerts.push(['Analytics integrity needs attention',`${num((integrity.issues||[]).length)} consistency issue(s) detected. Product and booking operations may still be healthy.`]);else if(integrity.status==='warning')alerts.push(['Analytics integrity warning',`${num((integrity.issues||[]).length)} analytics consistency warning(s) detected.`]);if(s.analytics_provider?.status!=='fresh')alerts.push(['Analytics degraded','PostHog is unavailable or stale. Product and booking operations are unaffected.']);if(!complete)alerts.push(['Catalogue incomplete',`${num(unique)} unique fixtures indexed. Provider total estimate: ${declared==null?'unknown':num(declared)}. Raw records: ${num(sb.raw_fetched_records)}.`]);if((b.no_code_rate||0)>.1)alerts.push(['No-code rate needs attention',`${pct(b.no_code_rate)} of automated bookings did not produce a usable code.`]);if((s.analytics_quality?.geo_coverage??1)<.7)alerts.push(['Analytics geo coverage degraded',`${pct(s.analytics_quality.geo_coverage)} of user events have trusted country metadata.`]);if(b.validation_failed)alerts.push(['Code validation failures',`${b.validation_failed} generated code(s) failed read-back validation.`]);if(last?.failed?.length)alerts.push(['Daily run incomplete',last.failed.join(', ')]);if(!alerts.length)alerts.push(['All key systems look healthy','No high-priority operational warnings in this period.']);/* alert-severity-v2 */$('alerts').innerHTML=alerts.map(a=>{const good=a[0]==='All key systems look healthy';return `<div class="alert ${good?'alert-ok':'alert-warn'}"><div class="alert-icon">${good?'&#10003;':'!'}</div><div><strong>${esc(a[0])}</strong><p>${esc(a[1])}</p></div></div>`}).join('')}
const countryNames=typeof Intl.DisplayNames==='function'?new Intl.DisplayNames([navigator.language],{type:'region'}):null;const countryLabel=code=>code==='unknown'?'Unknown':(countryNames?.of(code)||code);
function qualityCell(label,value){const cls=value==null?'neutral':value>=.9?'ok':value>=.7?'warning':'bad';return`<div class="retention-cell"><strong>${pct(value)}</strong><span>${esc(label)}</span><div class="status ${cls}">${value==null?'Awaiting data':value>=.9?'Healthy':value>=.7?'Watch':'Degraded'}</div></div>`}
function audienceTable(rows,label=x=>x){return table(['Segment','Visitors','Returning','Sessions','Prediction viewers','Builders','Code copiers','Copy conversion'],(rows||[]).map(r=>`<tr><td><strong>${esc(label(r.key))}</strong></td><td class="num">${num(r.visitors)}</td><td class="num">${num(r.returning)}</td><td class="num">${num(r.sessions)}</td><td class="num">${num(r.prediction_viewers)}</td><td class="num">${num(r.builders)}</td><td class="num">${num(r.code_copiers)}</td><td class="num">${pct(r.copy_conversion)}</td></tr>`))}
function deviceTable(rows){return table(['Device','Visitors','Prediction rate','Builder rate','Copy conversion','SportyBet open rate','Return rate'],(rows||[]).map(r=>`<tr><td><strong>${esc(r.key)}</strong></td><td class="num">${num(r.visitors)}</td><td class="num">${pct(r.prediction_view_rate)}</td><td class="num">${pct(r.builder_usage_rate)}</td><td class="num">${pct(r.copy_conversion)}</td><td class="num">${pct(r.sportybet_open_rate)}</td><td class="num">${pct(r.return_rate)}</td></tr>`))}
function renderAudience(){const s=DASH.summary,a=s.active_users||{},q=s.analytics_quality||{},pr=s.prediction_day_return||{};$('activeUsers').innerHTML=[kpi('Daily active',a.dau,'dau'),kpi('Weekly active',a.wau,'wau'),kpi('Monthly active',a.mau,'mau'),kpi('New visitors',s.totals.new_visitors,'new_visitors'),kpi('Returning',s.totals.returning_visitors,'returning_visitors',true),kpi('Prediction day return',pr.rate,'prediction_day_return',false,'pct')].join('');$('retention').innerHTML=Object.entries(s.retention||{}).map(([k,v])=>`<div class="retention-cell"><strong>${pct(v.rate)}</strong><span>${esc(k)} retention</span><div class="muted">${v.returned}/${v.eligible} eligible</div></div>`).join('');$('quality').innerHTML=[qualityCell('Geo coverage',q.geo_coverage),qualityCell('Device detection',q.device_coverage),qualityCell('OS detection',q.os_coverage),qualityCell('Browser detection',q.browser_coverage),qualityCell('Referrer attribution',q.referrer_attribution),qualityCell('Stable visitor IDs',q.stable_visitor_coverage)].join('');$('countries').innerHTML=audienceTable(s.by_country,countryLabel);$('devices').innerHTML=deviceTable(s.by_device);$('os').innerHTML=audienceTable(s.by_os);$('browsers').innerHTML=audienceTable(s.by_browser);$('traffic').innerHTML=audienceTable(s.by_source)}
function renderSporty(){const s=DASH.summary,b=s.booking,sb=s.sportybet||{};$('sportyKpis').innerHTML=[kpi('Automated attempts',b.attempts,'attempts'),kpi('Full success',b.full,'full',true),kpi('Rebuilt full',b.rebuilt,'rebuilt'),kpi('Partial',b.partial,'partial'),kpi('Validation success',b.validation_success_rate,'validation_success_rate',false,'pct'),kpi('No-code rate',b.no_code_rate,'no_code_rate',false,'pct')].join('');$('userBooking').innerHTML=[kpi('Valid code viewers',s.totals.valid_code_viewers,'valid_code_viewers'),kpi('Unique code copiers',s.totals.unique_code_copiers,'unique_code_copiers',true),kpi('Copy actions',s.totals.total_copy_actions,'total_copy_actions'),kpi('SportyBet openers',s.totals.sportybet_openers,'sportybet_openers')].join('');$('catalogue').innerHTML=`<div class="metric-list"><div class="metric-row"><strong>Provider fixture total (estimate)</strong><span>${maybeNum(sb.declared_total)}</span></div><div class="metric-row"><strong>Raw fetched records</strong><span>${maybeNum(sb.raw_fetched_records??sb.fetched_total)}</span></div><div class="metric-row"><strong>Unique indexed fixtures</strong><span>${maybeNum(sb.unique_indexed_fixtures??sb.fixtures)}</span></div><div class="metric-row"><strong>Duplicates removed</strong><span>${maybeNum(sb.duplicates_removed)}</span></div><div class="metric-row"><strong>Invalid records</strong><span>${maybeNum(sb.invalid_records)}</span></div><div class="metric-row"><strong>Catalogue complete</strong><span class="status ${sb.is_complete===true?'ok':'bad'}">${sb.is_complete===true?'Yes':'No'}</span></div><div class="metric-row"><strong>Priced markets</strong><span>${maybeNum(sb.priced_markets)}</span></div><div class="metric-row"><strong>Cache age</strong><span>${sb.cache_age_hours==null?'—':sb.cache_age_hours+'h'}</span></div></div>`;$('tierBooking').innerHTML=table(['Tier','Generated','Full','Rebuilt','Partial','No code','Avg odds'],(b.by_tier||[]).map(r=>`<tr><td><strong>${esc(r.tier)}</strong></td><td class="num">${num(r.generated)}</td><td class="num">${num(r.full)}</td><td class="num">${num(r.rebuilt)}</td><td class="num">${num(r.partial)}</td><td class="num">${num((r.unavailable||0)+(r.failed||0)+(r.validation_failed||0))}</td><td class="num">${r.avg_actual_odds??'—'}</td></tr>`));$('failures').innerHTML=table(['Failure reason','Tier','Count'],(b.failures||[]).map(r=>`<tr><td>${esc(r.reason)}</td><td>${esc(r.tier||'unknown')}</td><td class="num">${num(r.count)}</td></tr>`))}
function renderProduct(){const s=DASH.summary,b=s.builder||{},bb=s.builder_backend||{};$('builderKpis').innerHTML=[kpi('Builder users',s.totals.builder_users,'builder_users'),kpi('Server requests',bb.requests,'slip_builds'),kpi('Tickets produced',bb.tickets_produced,'valid_code_viewers',true),kpi('Ticket rate',bb.ticket_rate,'code_copy_rate',false,'pct'),kpi('Average legs',b.average_legs,'average_legs'),kpi('Average actual odds',b.average_actual_odds,'actual_odds')].join('');$('targets').innerHTML=bars((bb.by_target||[]).map(r=>({key:r.target,visitors:r.requests})));$('features').innerHTML=audienceTable(s.by_product_source);const perf=Object.entries(s.prediction_performance||{});$('performance').innerHTML=table(['Tier','Settled','Won','Lost','Accuracy','ROI','Profit'],perf.map(([tier,r])=>`<tr><td><strong>${esc(tier)}</strong></td><td class="num">${num(r.settled)}</td><td class="num">${num(r.won)}</td><td class="num">${num(r.lost)}</td><td class="num">${pct(r.win_rate)}</td><td class="num">${pct(r.roi)}</td><td class="num">${r.profit??0}</td></tr>`))}
function renderAnalyticsHealth(){const s=DASH.summary,h=s.analytics_health||{},p=h.provider||{},q=h.quality||{},c=s.metric_contracts||{},i=s.analytics_integrity||{};$('providerHealth').innerHTML=`<div class="health-grid"><div class="health-item"><div class="health-label">Human analytics</div><div class="health-value">${sourceLine(p)}</div><div class="muted">${esc(p.reason||'PostHog Query API responding')}</div></div><div class="health-item"><div class="health-label">Analytics integrity</div><div class="health-value"><span class="status ${i.status==='healthy'?'ok':i.status==='error'?'bad':'warning'}">${esc(i.status||'unknown')}</span></div><div class="muted">${esc((i.issues||[]).map(x=>x.code).join(', ')||'All funnel checks pass')}</div></div><div class="health-item"><div class="health-label">Backend facts</div><div class="health-value">${sourceLine(s.sources?.backend_facts)}</div></div><div class="health-item"><div class="health-label">Dual validation ends</div><div class="health-value">${esc(h.dual_write_until||'not set')}</div><div class="muted">Migration remains open until live events are verified.</div></div></div>`;$('quality').innerHTML=[qualityCell('Geo coverage',q.geo_coverage),qualityCell('Device detection',q.device_coverage),qualityCell('OS detection',q.os_coverage),qualityCell('Browser detection',q.browser_coverage),qualityCell('Referrer attribution',q.referrer_attribution),qualityCell('Stable visitor IDs',q.stable_visitor_coverage)].join('');$('rateContracts').innerHTML=table(['Metric','Numerator','Denominator','Rate','Sample'],Object.entries(c).map(([name,v])=>`<tr><td>${esc(name)}</td><td class="num">${num(v.numerator)}</td><td class="num">${num(v.denominator)}</td><td class="num">${pct(v.rate)}</td><td><span class="status ${v.sample_status==='normal'?'ok':'warning'}">${esc(v.sample_status)}</span></td></tr>`))}
function dateISO(d){return d.toISOString().slice(0,10)}
async function loadDashboard(){
 const active=document.querySelector('.range button.active');
 const days=active?.dataset.days||'1';
 let q='?days='+days;

 if(days==='yesterday'){
  const d=new Date();
  d.setUTCDate(d.getUTCDate()-1);
  q=`?start=${dateISO(d)}&end=${dateISO(d)}`;
 }

 if(days==='custom'){
  if(!$('dateStart').value||!$('dateEnd').value)return;
  q=`?start=${$('dateStart').value}&end=${$('dateEnd').value}`;
 }

 document.body.classList.add('dashboard-loading');
 $('period').textContent='Refreshing dashboard...';

 try{
  const [d,s]=await Promise.all([
   api('/analytics'+q),
   api('/status')
  ]);

  DASH=d;
  SETTINGS=s.settings||{};

  const envRaw=String(s.environment||'production').toLowerCase();
  const envLabel=envRaw==='production'?'Live':envRaw==='staging'?'Staging':envRaw;
  const envPill=document.querySelector('.env-pill');
  if(envPill)envPill.innerHTML='<span class="env-dot"></span>'+esc(envLabel);

  $('period').textContent=`${d.summary.start} \u2192 ${d.summary.end}`;

  renderOverview();
  renderAudience();
  renderSporty();
  renderProduct();
  renderAnalyticsHealth();
 }catch(e){
  $('period').textContent='Dashboard unavailable';
  $('toast').textContent=e.message;
  $('toast').classList.remove('hidden');
 }finally{
  document.body.classList.remove('dashboard-loading');
 }
}
async function loadContent(){const p=$('fPlatform').value,st=$('fStatus').value;try{const d=await api('/content?limit=400'+(p?'&platform='+p:'')+(st?'&status='+st:''));$('contentTable').innerHTML=table(['Template','Platform','Status','Date','Actions'],d.content.map(c=>`<tr><td>${esc(c.template)}</td><td>${esc(c.platform)}</td><td><span class="tag ${esc(c.status)}">${esc(c.status)}</span></td><td>${esc(c.publish_date)}</td><td class="row wrap"><button class="btn" data-act="preview" data-id="${c.id}">View</button>${c.status==='DRAFT'?`<button class="btn" data-act="approve" data-id="${c.id}">Approve</button>`:''}${!['instagram','facebook','tiktok','youtube','x'].includes(c.platform)&&c.status!=='PUBLISHED'?`<button class="btn btn-primary" data-act="publish" data-id="${c.id}">Publish</button>`:''}</td></tr>`))}catch(e){$('contentTable').innerHTML=empty(e.message)}}
async function preview(id){const d=await api('/content?limit=400'),c=d.content.find(x=>x.id===id);if(!c)return;const p=c.payload||{};$('previewBody').textContent=p.text||p.caption||JSON.stringify(p,null,2);$('preview').classList.remove('hidden')}
async function act(id,what){try{await api(`/content/${id}/${what}`,{method:'POST'});loadContent()}catch(e){alert(e.message)}}
async function generate(publish){try{const d=await api('/generate?publish='+publish,{method:'POST'}),r=d.report;alert(`Generated ${r.generated}; stored ${r.stored}; published ${r.published.length}; failed ${r.failed.length}.`);loadContent()}catch(e){alert(e.message)}}
async function retry(){try{const d=await api('/retry',{method:'POST'});alert(`Retried ${d.attempted}; recovered ${d.recovered}.`);loadPubs()}catch(e){alert(e.message)}}
async function loadPubs(){try{const d=await api('/publications?limit=300');$('pubTable').innerHTML=table(['Date','Channel','Template','Status','Tries','Detail'],d.publications.map(p=>`<tr><td>${esc(p.publish_date)}</td><td>${esc(p.channel)}</td><td>${esc(p.template)}</td><td><span class="tag ${esc(p.status)}">${esc(p.status)}</span></td><td class="num">${p.attempts}</td><td class="muted">${esc(p.last_error?.slice(0,80)||p.external_id||'')}</td></tr>`))}catch(e){$('pubTable').innerHTML=empty(e.message)}}
async function loadSettings(){try{const d=await api('/settings');SETTINGS=d.settings;const toggles=(obj,prefix)=>Object.entries(obj||{}).map(([k,v])=>`<div class="switch"><span>${esc(k)}</span><input type="checkbox" id="${prefix}_${esc(k)}" ${v?'checked':''}></div>`).join('');$('engineToggle').innerHTML=`<div class="switch"><span>Growth Engine enabled</span><input type="checkbox" id="s_engine" ${SETTINGS.engine_enabled?'checked':''}></div>`;$('channelToggles').innerHTML=toggles(SETTINGS.channel_enabled,'ch');$('autoToggles').innerHTML=toggles(SETTINGS.channel_auto_publish,'auto');$('scheduleFields').innerHTML=Object.entries(SETTINGS.schedule||{}).map(([k,v])=>`<div class="switch"><span>${esc(k)}</span><input class="field" id="sch_${esc(k)}" value="${esc(v)}"></div>`).join('')}catch(e){}}
async function saveSettings(){const ch={},auto={},sch={};Object.keys(SETTINGS.channel_enabled||{}).forEach(k=>ch[k]=$('ch_'+k).checked);Object.keys(SETTINGS.channel_auto_publish||{}).forEach(k=>auto[k]=$('auto_'+k).checked);Object.keys(SETTINGS.schedule||{}).forEach(k=>sch[k]=$('sch_'+k).value.trim());try{await api('/settings',{method:'POST',body:JSON.stringify({engine_enabled:$('s_engine').checked,channel_enabled:ch,channel_auto_publish:auto,schedule:sch})});$('settingsMsg').textContent='Settings saved'}catch(e){$('settingsMsg').textContent=e.message}}
async function loadRefs(){try{const d=await api('/referrals');$('refTable').innerHTML=table(['Code','Name','Link'],d.referrals.map(r=>{const link=`https://www.betsightly.com/predictions?utm_source=referral&utm_medium=referral&utm_campaign=creator&ref=${encodeURIComponent(r.code)}`;return`<tr><td><code>${esc(r.code)}</code></td><td>${esc(r.name||'')}</td><td>${esc(link)}</td></tr>`}))}catch(e){}}
async function addRef(){try{await api('/referrals',{method:'POST',body:JSON.stringify({code:$('refCode').value,name:$('refName').value})});$('refCode').value=$('refName').value='';loadRefs()}catch(e){$('refErr').textContent=e.message}}
const ACTIONS={login,logout,retry,'generate':()=>generate(false),'generate-publish':()=>generate(true),'save-settings':saveSettings,'add-ref':addRef,preview:e=>preview(Number(e.dataset.id)),approve:e=>act(Number(e.dataset.id),'approve'),publish:e=>act(Number(e.dataset.id),'publish'),'menu':()=>$('side').classList.toggle('open'),'apply-range':loadDashboard};
document.addEventListener('click',e=>{const el=e.target.closest('[data-act],[data-page],[data-days]');if(!el)return;if(el.dataset.page){nav(el.dataset.page,el);return}if(el.dataset.days){document.querySelectorAll('.range button').forEach(b=>b.classList.remove('active'));el.classList.add('active');$('customDates').classList.toggle('hidden',el.dataset.days!=='custom');if(el.dataset.days!=='custom')loadDashboard();return}const fn=ACTIONS[el.dataset.act];if(fn){e.preventDefault();fn(el)}});
document.addEventListener('change',e=>{if(e.target.dataset.change==='content')loadContent()});$('pw').addEventListener('keydown',e=>{if(e.key==='Enter')login()});
async function boot(){$('today').textContent=new Date().toLocaleDateString(undefined,{weekday:'long',day:'numeric',month:'short'});await loadDashboard();const s=SETTINGS.channel_enabled||{},sel=$('fPlatform');if(sel.options.length===1)Object.keys(s).forEach(ch=>sel.add(new Option(ch,ch)))}
(async()=>{try{const c=await(await fetch(API+'/admin/config')).json();if(!c.configured)$('cfgNote').textContent='Admin login is not configured on this server.'}catch(e){}try{await api('/admin/me');show('app');boot()}catch(e){show('login')}})();
"""

ADMIN_HTML = r"""<!doctype html><html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><meta name="robots" content="noindex,nofollow"><meta name="theme-color" content="#090d0b"><title>BetSightly Command Center</title><link rel="stylesheet" href="/admin/app.css"></head><body>
<section id="login" class="login-shell"><div class="login-card"><div class="brand"><span class="brand-mark">B</span><span>BetSightly</span></div><h1>Command center</h1><p>Product growth, prediction performance and SportyBet operations in one place.</p><input id="pw" class="field" type="password" placeholder="Admin password" autocomplete="current-password"><p id="loginErr" class="error"></p><button class="btn btn-primary btn-wide" data-act="login">Enter dashboard</button><p id="cfgNote" class="muted"></p></div></section>
<div id="app" class="shell hidden"><aside id="side" class="sidebar"><div class="brand"><span class="brand-mark">B</span><span>BetSightly</span></div><div class="nav-label">Command center</div><nav class="nav"><button class="active" data-page="overview"><span class="nav-icon">◫</span>Overview</button><button data-page="audience"><span class="nav-icon">◎</span>Users & retention</button><button data-page="product"><span class="nav-icon">◇</span>Product & predictions</button><button data-page="sporty"><span class="nav-icon">S</span>SportyBet</button></nav><div class="nav-label">Operations</div><nav class="nav"><button data-page="analytics-health"><span class="nav-icon">♥</span>Analytics health</button><button data-page="content"><span class="nav-icon">✦</span>Content</button><button data-page="publishing"><span class="nav-icon">↗</span>Publishing</button><button data-page="referrals"><span class="nav-icon">⌁</span>Referrals</button><button data-page="settings"><span class="nav-icon">⚙</span>Settings</button></nav><div class="sidebar-foot"><div class="live"><span class="dot"></span>Protected admin session</div><button class="btn btn-ghost btn-danger btn-wide" data-act="logout">Sign out</button></div></aside>
<div class="workspace"><header class="topbar"><div class="row"><button class="btn mobile-toggle" data-act="menu">☰</button><div class="topbar-title"><div class="topbar-heading"><strong>Operations dashboard</strong><span class="env-pill"><span class="env-dot"></span>Live</span></div><span id="today"></span></div></div><div class="actions"><span id="period" class="muted"></span><button class="btn desktop-action" data-act="generate">Generate content</button><button class="btn btn-primary desktop-action" data-act="generate-publish">Generate + publish</button></div></header><div id="toast" class="note hidden"></div>
<main>
<section id="page-overview" class="page active"><div class="page-head"><div><p class="eyebrow">Business overview</p><h1>Today at BetSightly</h1><p>Usage, conversion and operational health—without vanity metrics.</p></div><div><div class="range"><button class="active" data-days="1">Today</button><button data-days="yesterday">Yesterday</button><button data-days="7">7 days</button><button data-days="30">30 days</button><button data-days="90">90 days</button><button data-days="custom">Custom</button></div><div id="customDates" class="row hidden"><input id="dateStart" class="field" type="date"><input id="dateEnd" class="field" type="date"><button class="btn" data-act="apply-range">Apply</button></div></div></div>
<div class="section"><div class="section-head"><h2>Today’s health</h2><p>Can customers use the product right now?</p></div><div id="health" class="card card-flush health-grid"></div></div>
<div class="section"><div class="section-head"><h2>Audience</h2><p>Actual user activity only</p></div><div id="audienceKpis" class="grid kpis"></div></div>
<div class="section"><div class="section-head"><h2>Product engagement</h2><p>Unique people and valid-code conversion</p></div><div id="engagementKpis" class="grid kpis"></div></div>
<div class="section"><div class="section-head"><h2>Operational health</h2><p>Automated backend generation—not user attempts</p></div><div id="systemKpis" class="grid kpis"></div></div>
<div class="grid overview-funnel-grid section"><article class="card"><div class="card-title"><h3>Prediction funnel</h3><span class="muted">Unique user progression</span></div><div id="predictionFunnel" class="funnel"></div></article><article class="card"><div class="card-title"><h3>Builder funnel</h3></div><div id="builderFunnel" class="funnel"></div></article><article class="card"><div class="card-title"><h3>Rollover funnel</h3></div><div id="rolloverFunnel" class="funnel"></div></article><article class="card"><div class="card-title"><h3>Actionable alerts</h3></div><div id="alerts"></div></article></div>
<div class="grid overview-insight-grid section"><article class="card span-2"><div class="card-title"><h3>Visitor trend</h3><div class="legend"><span>● Visitors</span></div></div><div id="trend"></div></article><article class="card"><div class="card-title"><h3>Top product areas</h3></div><div id="topPages"></div></article><article class="card"><div class="card-title"><h3>Traffic sources</h3></div><div id="sourcesMini"></div></article></div></section>
<section id="page-audience" class="page"><div class="page-head"><div><p class="eyebrow">Audience intelligence</p><h1>Users & retention</h1><p>Do people return for tomorrow’s predictions?</p></div></div><div id="activeUsers" class="grid kpis"></div><div class="section"><div class="section-head"><h2>Retention cohorts</h2><p>Privacy-safe browser identifier; anonymous and approximate.</p></div><div class="card"><div id="retention" class="retention"></div></div></div><div class="section"><div class="section-head"><h2>Countries</h2><p>Provider-enriched geography; no GPS.</p></div><div id="countries" class="card card-flush"></div></div><div class="section"><div class="section-head"><h2>Traffic-source quality</h2><p>UTM and first-session referrer attribution</p></div><div id="traffic" class="card card-flush"></div></div><div class="section"><div class="section-head"><h2>Mobile quality</h2><p>Conversion and return behaviour by device</p></div><div id="devices" class="card card-flush"></div></div><div class="grid two section"><article class="card card-flush"><div class="card-title"><h3>Operating systems</h3></div><div id="os"></div></article><article class="card card-flush"><div class="card-title"><h3>Browsers</h3></div><div id="browsers"></div></article></div></section>
<section id="page-analytics-health" class="page"><div class="page-head"><div><p class="eyebrow">Data operations</p><h1>Analytics health</h1><p>Provider freshness, enrichment coverage, rate denominators and migration status.</p></div></div><div id="providerHealth" class="card card-flush"></div><div class="section"><div class="section-head"><h2>Data quality</h2><p>Unknown values remain visible; historical data is never fabricated.</p></div><div class="card"><div id="quality" class="retention"></div></div></div><div class="section"><div class="section-head"><h2>Rate contracts</h2><p>Raw numerators and denominators; small samples are labelled.</p></div><div id="rateContracts" class="card card-flush"></div></div></section>
<section id="page-product" class="page"><div class="page-head"><div><p class="eyebrow">Product intelligence</p><h1>Builder & predictions</h1><p>Usage and betting performance remain separate, so availability never masquerades as accuracy.</p></div></div><div id="builderKpis" class="grid kpis"></div><div class="grid two section"><article class="card"><div class="card-title"><h3>Builder target odds</h3></div><div id="targets"></div></article><article class="card card-flush"><div class="card-title"><h3>Feature usage</h3></div><div id="features"></div></article></div><div class="section"><div class="section-head"><h2>Prediction performance</h2><p>Settled record and level-stake ROI</p></div><div id="performance" class="card card-flush"></div></div></section>
<section id="page-sporty" class="page"><div class="page-head"><div><p class="eyebrow">Booking operations</p><h1>SportyBet health</h1><p>Code creation, validation, recovery and failure diagnosis.</p></div></div><div class="section-head"><h2>System booking health</h2><p>Automated pipeline activity</p></div><div id="sportyKpis" class="grid kpis"></div><div class="section"><div class="section-head"><h2>User booking engagement</h2><p>Human views and actions; copies are not bets placed.</p></div><div id="userBooking" class="grid kpis"></div></div><div class="grid three section"><article class="card"><div class="card-title"><h3>Catalogue health</h3></div><div id="catalogue"></div></article><article class="card span-2 card-flush"><div class="card-title"><h3>Booking by tier</h3></div><div id="tierBooking"></div></article></div><div class="section"><div class="section-head"><h2>Failure reasons</h2><p>Code copied is never treated as bet placed.</p></div><div id="failures" class="card card-flush"></div></div></section>
<section id="page-content" class="page"><div class="page-head"><div><p class="eyebrow">Growth engine</p><h1>Content</h1><p>Review and publish campaign assets.</p></div><button class="btn" data-act="retry">Retry failed</button></div><div class="note">Social betting content remains approval-first where platform policy requires manual publishing.</div><div class="row wrap section"><select id="fPlatform" class="field" data-change="content"><option value="">All platforms</option></select><select id="fStatus" class="field" data-change="content"><option value="">All statuses</option><option>DRAFT</option><option>APPROVED</option><option>PUBLISHED</option><option>FAILED</option></select></div><div id="contentTable" class="card card-flush section"></div><div id="preview" class="card hidden section"><pre id="previewBody"></pre></div></section>
<section id="page-publishing" class="page"><div class="page-head"><div><p class="eyebrow">Distribution</p><h1>Publishing history</h1><p>Delivery state across every configured channel.</p></div><button class="btn" data-act="retry">Retry failures</button></div><div id="pubTable" class="card card-flush"></div></section>
<section id="page-referrals" class="page"><div class="page-head"><div><p class="eyebrow">Acquisition</p><h1>Referral links</h1></div></div><div class="card"><div class="row wrap"><input id="refCode" class="field" placeholder="Referral code"><input id="refName" class="field" placeholder="Partner name"><button class="btn btn-primary" data-act="add-ref">Create link</button></div><p id="refErr" class="error"></p></div><div id="refTable" class="card card-flush section"></div></section>
<section id="page-settings" class="page"><div class="page-head"><div><p class="eyebrow">Configuration</p><h1>Growth settings</h1></div><button class="btn btn-primary" data-act="save-settings">Save changes</button></div><div class="grid two"><article class="card"><div class="card-title"><h3>Engine</h3></div><div id="engineToggle"></div></article><article class="card"><div class="card-title"><h3>Channels</h3></div><div id="channelToggles"></div></article><article class="card"><div class="card-title"><h3>Auto-publish</h3></div><div id="autoToggles"></div></article><article class="card"><div class="card-title"><h3>Schedule · UTC</h3></div><div id="scheduleFields"></div></article></div><p id="settingsMsg" class="muted"></p></section>
</main></div></div><script src="/admin/app.js"></script></body></html>"""

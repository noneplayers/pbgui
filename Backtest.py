import streamlit as st
from bokeh.plotting import figure
from bokeh.palettes import Category20_20
from bokeh.models import NumeralTickFormatter, HoverTool
import json
import psutil
import sys
import subprocess
import shlex
import glob
import configparser
import time
import multiprocessing
import pandas as pd
from pbgui_func import validateJSON, config_pretty_str
import uuid
from Base import Base
from Config import Config
from pathlib import Path, PurePath
from shutil import rmtree
import requests
import datetime

class BacktestItem(Base):
    def __init__(self, config: str = None):
        super().__init__()
        self._config = Config(config=config)
        self.file = None
        self.log = None
        self.sd = None
        self.ed = None
        self.sb = None
        self.pbdir = None
        self.initialize()

    @property
    def config(self): return self._config.config

    def initialize(self):
        self.sd = (datetime.date.today() - datetime.timedelta(days=365*4)).strftime("%Y-%m-%d")
        self.ed = datetime.date.today().strftime("%Y-%m-%d")
        self.sb = 1000

    def import_pbconfigdb(self):
        st.markdown('### Import from PassivBot Config Result DB by [Scud](%s)' % "https://pbconfigdb.scud.dedyn.io/")
        df = self.update_pbconfigdb()
        df = df[df['source'].str.contains('github')]
        df_min = df[[
            "symbol", 
            "side", 
            "strategy", 
            "adg_per_exposure", 
            "adg_weighted_per_exposure", 
            "eqbal_ratio_mean_of_10_worst", 
            "hrs_stuck_max", 
            "loss_profit_ratio", 
            "pa_distance_max", 
            "n_days", 
            "net_pnl_plus_fees", 
            "quality_score", 
            "balance_needed",
            "source",
            "hash"]]
        column_config = {
            "_index": 'Id',
            "View": st.column_config.CheckboxColumn('View', default=False),
            "adg_per_exposure": 'adg_pe',
            "adg_weighted_per_exposure": 'adg_wpe',
            "eqbal_ratio_mean_of_10_worst": 'eqbal_10_worst',
            "balance_needed": 'min_balance',
            "quality_score": 'score',
            "source": st.column_config.LinkColumn('source', width=None, disabled=True),
            "hash": None
            }
        df_min.insert(0 ,column="View", value=False)
        col_symbol, col_side, col_strategy = st.columns([1,1,1])
        with col_symbol:
            symbols = st.multiselect("Symbols", df["symbol"].unique(), default=None, key=None, on_change=None, args=None)
            adg_per_exposure = st.number_input("adg_per_exposure =>", min_value=0.0, max_value=1.0, value=0.0, step=0.05, format="%.2f")
            if symbols:
                df_min = df_min[df_min['symbol'].isin(symbols)]
            df_min = df_min[df_min['adg_per_exposure'].ge(adg_per_exposure)]
        with col_side:
            side = st.multiselect("Side", df["side"].unique(), default=None, key=None, on_change=None, args=None)
            hrs_stuck_max = st.number_input("hrs_stuck_max <=", min_value=df["hrs_stuck_max"].min(), max_value=df["hrs_stuck_max"].max(), value=df["hrs_stuck_max"].max(), step=1.0, format="%.1f")
            if side:
                df_min = df_min[df_min['side'].isin(side)]
            df_min = df_min[df_min['hrs_stuck_max'].le(hrs_stuck_max)]
        with col_strategy:
            strategy = st.multiselect("Strategy", df["strategy"].unique(), default=None, key=None, on_change=None, args=None)
            quality_score = st.number_input("quality_score =>", min_value=df["quality_score"].min(), max_value=df["quality_score"].max(), value=df["quality_score"].min(), step=1.0, format="%.1f")
            if strategy:
                df_min = df_min[df_min['strategy'].isin(strategy)]
            df_min = df_min[df_min['quality_score'].ge(quality_score)]
        df_min = df_min.reset_index(drop=True)
        selected = st.data_editor(data=df_min, width=None, height=None, use_container_width=True, hide_index=None, column_order=None, column_config=column_config)
        col_image, col_config = st.columns([1,1])
        view = selected[selected['View']==True]
        view = view.reset_index()
        for index, row in view.iterrows():
            col_image, col_config = st.columns([1,1])
            with col_image:
                hash = row['hash']
                source = row['source']
                id = row["index"]
                config = self.fetch_config(source)
                if not config.endswith("found"):
                    if st.checkbox(f'{id}: Backtest', key=hash):
                        self._config.config = config
                        self.symbol = row['symbol']
                        del st.session_state.bt_import
                        st.experimental_rerun()
                st.image(f'https://pbconfigdb.scud.dedyn.io/plots/{hash}.webp')
            with col_config:
                st.code(config)

    def fetch_config(self, url: str):
        response = requests.get(url)
        if response.status_code == 200:
            config = response.json()["payload"]["blob"]["rawLines"]
            config = '\n'.join(config)
            if validateJSON(config):
                t = json.loads(config)
                t["config_name"] = json.loads(config)["config_name"][:60]
                return config_pretty_str(t)
        return f'{response.status_code} config not found'

    def update_pbconfigdb(self):
        day = 24*60*60
        url = "https://pbconfigdb.scud.dedyn.io/result/pbconfigdb.pbgui.json"
        pbgdir = Path.cwd()
        local = Path(f'{pbgdir}/data/pbconfigdb')
        if not local.exists():
            local.mkdir(parents=True)
        dbfile = Path(f'{local}/pbconfigdb.json')
        if dbfile.exists():
            dbfile_ts = dbfile.stat().st_mtime
            now_ts = datetime.datetime.now().timestamp()
            if dbfile_ts < now_ts-day:
                df = pd.read_json(url)
                df.to_json(dbfile)
            else:
                df = pd.read_json(dbfile)
        else:
            df = pd.read_json(url)
            df.to_json(dbfile)
        return df

    def edit_config(self):
        self._config.edit_config()

    def load(self, file: str):
        self.file = Path(file)
        self._config = Config(f'{self.file}.cfg')
        self._config.load_config()
        self.log = Path(f'{self.file}.log')
        with open(self.file, "r", encoding='utf-8') as f:
            t = json.load(f)
            if t["market_type"] == "futures":
                self._market_type = "swap"
            else:
                self._market_type = "spot"
            self.user = t["user"]
            self.symbol = t["symbol"]
            self.sd = t["sd"]
            self.ed = t["ed"]
            self.sb = t["sb"]

    def save(self):
        pbgdir = Path.cwd()
        dest = Path(f'{pbgdir}/data/bt_queue')
        unique_filename = str(uuid.uuid4())
        if not self.file:
            self.file = Path(f'{dest}/{unique_filename}.json') 
        bt_dict = {
            "user": self.user,
            "symbol": self.symbol,
            "sd": self.sd,
            "ed": self.ed,
            "sb": self.sb,
            "market_type": self.market_type,
        }
        if not dest.exists():
            dest.mkdir(parents=True)
        self._config.config_file = f'{self.file}.cfg'
        self._config.save_config()
        with open(self.file, "w", encoding='utf-8') as f:
            json.dump(bt_dict, f, indent=4)

    def remove(self):
        self.file.unlink(missing_ok=True)
        self.log.unlink(missing_ok=True)
        Path(self._config.config_file).unlink(missing_ok=True)

    def remove_log(self):
        self.log.unlink(missing_ok=True)

    def load_log(self):
        if self.log:
            if self.log.exists():
                with open(self.log, 'r', encoding='utf-8') as f:
                    return f.read()

    def status(self):
        if self.is_running():
            return "running"
        if self.is_finish():
            return "complete"
        if self.is_error():
            return "error"
        else:
            return "not started"

    def is_running(self):
        if self.pid():
            return True
        return False

    def is_finish(self):
        log = self.load_log()
        if log:
            if "Summary" in log:
                return True
            else:
                return False
        else:
            return False

    def is_error(self):
        log = self.load_log()
        if log:
            if "Summary" in log:
                return False
            else:
                return True
        else:
            return False

    def stop(self):
        if self.is_running():
            self.pid().kill()

    def pid(self):
        if self.file:
            for process in psutil.process_iter():
                try:
                    cmdline = process.cmdline()
                except psutil.NoSuchProcess:
                    pass
                except psutil.AccessDenied:
                    pass
                if any(str(self.file) in sub for sub in cmdline) and any("backtest.py" in sub for sub in cmdline):
                    return process

    def run(self):
        if not self.is_finish() and not self.is_running():
            pb_config = configparser.ConfigParser()
            pb_config.read('pbgui.ini')
            if pb_config.has_option("main", "pbdir"):
                pbdir = pb_config.get("main", "pbdir")
                cmd = [sys.executable, '-u', PurePath(f'{pbdir}/backtest.py')]
                cmd_end = f'-dp -u {self.user} -s {self.symbol} -sd {self.sd} -ed {self.ed} -sb {self.sb} -m {self.market_type}'
                cmd.extend(shlex.split(cmd_end))
                cmd.extend(['-bd', PurePath(f'{pbdir}/backtests/pbgui'), PurePath(f'{str(self._config.config_file)}')])
                log = open(self.log,"w")
                subprocess.Popen(cmd, stdout=log, stderr=log, cwd=pbdir, text=True)

class BacktestQueue:
    def __init__(self):
        self.items = []
        self.pb_config = configparser.ConfigParser()
        self.pb_config.read('pbgui.ini')
        if not self.pb_config.has_section("backtest"):
            self.pb_config.add_section("backtest")
            self.pb_config.set("backtest", "autostart", "False")
            self.pb_config.set("backtest", "cpu", str(multiprocessing.cpu_count()-1))
        self._autostart = eval(self.pb_config.get("backtest", "autostart"))
        self._cpu = int(self.pb_config.get("backtest", "cpu"))
        if self._autostart:
            self.run()

    @property
    def cpu(self):
        self.pb_config.read('pbgui.ini')
        self._cpu = int(self.pb_config.get("backtest", "cpu"))
        return self._cpu

    @cpu.setter
    def cpu(self, new_cpu):
        if new_cpu != self._cpu:
            self._cpu = new_cpu
            self.pb_config.set("backtest", "cpu", str(self._cpu))
            with open('pbgui.ini', 'w') as f:
                self.pb_config.write(f)
            st.experimental_rerun()

    @property
    def autostart(self):
        return self._autostart

    @autostart.setter
    def autostart(self, new_autostart):
        if new_autostart != self._autostart:
            self._autostart = new_autostart
            self.pb_config.set("backtest", "autostart", str(self._autostart))
            with open('pbgui.ini', 'w') as f:
                self.pb_config.write(f)
            if self._autostart:
                self.run()
            else:
                self.stop()
            st.experimental_rerun()

    def add(self, item: BacktestItem = None):
        if item:
            self.items.append(item)

    def remove_finish(self):
        for item in self.items:
            if item.is_finish():
                item.remove()
        st.experimental_rerun()

    def running(self):
        r = 0
        for item in self.items:
            if item.is_running():
                r+=1
        return r
        
    def load(self):
        pbgdir = Path.cwd()
        dest = Path(f'{pbgdir}/data/bt_queue')
        p = str(Path(f'{dest}/*.json'))
        items = glob.glob(p)
        self.items = []
        for item in items:
            bt_item = BacktestItem()
            bt_item.load(item)
            if self.items:
                if not any(str(bt_item.file) in str(sub.file) for sub in self.items):
                    self.add(bt_item)
            else:
                self.add(bt_item)

    def run(self):
        if not self.is_running():
            pbgdir = Path.cwd()
            cmd = [sys.executable, '-u', PurePath(f'{pbgdir}/Backtest.py')]
            log = open(Path(f'{pbgdir}/data/bt_queue/Backtest.log'),"a")
            subprocess.Popen(cmd, stdout=log, stderr=log, cwd=pbgdir, text=True)

    def stop(self):
        if self.is_running():
            self.pid().kill()


    def is_running(self):
        if self.pid():
            return True
        return False

    def pid(self):
        for process in psutil.process_iter():
            try:
                cmdline = process.cmdline()
            except psutil.AccessDenied:
                continue
            if any("Backtest.py" in sub for sub in cmdline):
                return process

class BacktestResult:
    def __init__(self, backtest_path: str = None):
        self.backtest_path = backtest_path
        self.config = self.load_config()
        self.result = self.load_result()
        self.result_txt = self.load_result_txt()
        self.long = self.result["long"]
        self.short = self.result["short"]
        self.long_enabled = self.result["long"]["enabled"]
        self.short_enabled = self.result["short"]["enabled"]
        self.symbol = self.result["symbol"]
        self.sd = self.result["start_date"]
        self.ed = self.result["end_date"]
        self.sb = self.result["starting_balance"]
        self.exchange = self.result["exchange"]
        self.market_type = self.result["market_type"]
        self.stats = None
        self.selected = False

    def load_config(self):
        r = Path(f'{self.backtest_path}/live_config.json')
        with open(r, "r", encoding='utf-8') as f:
            return f.read()
    def load_result(self):
        r = Path(f'{self.backtest_path}/result.json')
        with open(r, "r", encoding='utf-8') as f:
            return json.load(f)
    def load_result_txt(self):
        r = Path(f'{self.backtest_path}/backtest_result.txt')
        with open(r, "r", encoding='utf-8') as f:
            return f.read()
    def load_stats(self):
        stats = f'{self.backtest_path}/stats.csv'
        self.stats = pd.read_csv(stats)

class BacktestResults:
    def __init__(self, backtest_path: str = None):
        self.backtest_path = backtest_path
        self.backtests = []
        self.symbols = []
        self.exchanges = []

    def remove(self, bt_result: BacktestResult):
        rmtree(bt_result.backtest_path, ignore_errors=True)
        self.backtests.remove(bt_result)

    def view(self, symbols: list = [], exchanges: list = [], trades: pd.DataFrame = None):
        if self.backtests or isinstance(trades, pd.DataFrame):
            d = []
            column_config = {
                "Show": st.column_config.CheckboxColumn('Show', default=False),
                "Delete": st.column_config.CheckboxColumn('Delete', default=False),
                }
            for bt in self.backtests:
                if (bt.symbol in symbols or not symbols) and (bt.exchange in exchanges or not exchanges):
                    if bt.market_type == "spot":
                        filename = str(bt.backtest_path).partition(f'{bt.exchange}_spot/')[-1]
                    else:
                        filename = str(bt.backtest_path).partition(f'{bt.exchange}/')[-1]
                    d.append({
                            'id': self.backtests.index(bt),
                            'Show': bt.selected,
                            'Symbol': bt.symbol,
                            'Exchange': bt.exchange,
                            'Start':  bt.sd,
                            'End': bt.ed,
                            'Balance': bt.sb,
                            'Market': bt.market_type,
                            'LE': bt.long_enabled,
                            'SE': bt.short_enabled,
                            'Name': filename,
                            'Delete': False,
                        }
                    )
            new_bt = st.data_editor(data=d, width=None, height=None, use_container_width=True, hide_index=None, column_order=None, column_config=column_config, disabled=['Symbol','Exchange','Start','End','Balance','Market','LE','SE','Name'])
            if new_bt != d:
                for line in new_bt:
                    if line["Delete"] == True:
                        self.remove(self.backtests[line["id"]])
                        st.experimental_rerun()
                    elif line["Show"] == True:
                        self.backtests[line["id"]].load_stats()
                        self.backtests[line["id"]].selected = True
                    else:
                        self.backtests[line["id"]].selected = False
                st.experimental_rerun()
        else:
            return
        hover_be = HoverTool(
            tooltips=[
                ( 'name',   '$name'            ),
                ( 'date',   '@x{%F}'            ),
                ( 'total', '@y{0.00} $'      ),
            ],

            formatters={
                '@x'           : 'datetime', # use 'datetime' formatter for '@date' field
            },

            # display a tooltip whenever the cursor is vertically in line with a glyph
            mode='mouse'
        )
        hover_we = HoverTool(
            tooltips=[
                ( 'name',   '$name'            ),
                ( 'date',   '@x{%F}'            ),
                ( 'total', '@y{0.00} WE'      ),
            ],

            formatters={
                '@x'           : 'datetime', # use 'datetime' formatter for '@date' field
            },

            # display a tooltip whenever the cursor is vertically in line with a glyph
            mode='mouse'
        )
        be = figure(
            x_axis_label='date',
            y_axis_label='USDT',
            x_axis_type='datetime',
            tools = "pan,box_zoom,wheel_zoom,save,reset",
            active_scroll="wheel_zoom")

        we = figure(
            x_axis_label='time',
            y_axis_label='WE',
            x_axis_type='datetime',
            tools = "pan,box_zoom,wheel_zoom,save,reset",
            active_scroll="wheel_zoom")
        b_long = {}
        e_long = {}
        b_short = {}
        e_short = {}
        we_long = {}
        we_short = {}
        color_b = -2
        color_e = -1
        if isinstance(trades, pd.DataFrame):
            color_b += 2
            color_e += 2
            x = trades["timestamp"]
            be.line(x, trades["balance"], legend_label=f'History',color=Category20_20[color_b], line_width=2, name=f'History')
        for idx, bt in enumerate(self.backtests):
            if bt.selected and bt.long_enabled:
                color_b += 2
                color_e += 2
                x = bt.stats["timestamp"]
                b_long[idx] = bt.stats["balance_long"]
                e_long[idx] = bt.stats["equity_long"]
                we_long[idx] = bt.stats["wallet_exposure_long"]
                be.line(x, b_long[idx], legend_label=f'{self.backtests.index(bt)}: {bt.exchange} {bt.symbol} {bt.sd} {bt.ed} long_balance',color=Category20_20[color_b], line_width=2, name=f'{self.backtests.index(bt)}: {bt.exchange} {bt.symbol} {bt.sd} {bt.ed} long_balance')
                be.line(x, e_long[idx], legend_label=f'{self.backtests.index(bt)}: {bt.exchange} {bt.symbol} {bt.sd} {bt.ed} long_equity',color=Category20_20[color_e], line_width=1, name=f'{self.backtests.index(bt)}: {bt.exchange} {bt.symbol} {bt.sd} {bt.ed} long_equity')
                we.line(x, we_long[idx], legend_label=f'{self.backtests.index(bt)}: {bt.exchange} {bt.symbol} {bt.sd} {bt.ed} wallet_exposure_long',color=Category20_20[color_b], line_width=1, name=f'{self.backtests.index(bt)}: {bt.exchange} {bt.symbol} {bt.sd} {bt.ed} wallet_exposure_long')
            if bt.selected and bt.short_enabled:
                x = bt.stats["timestamp"]
                b_short[idx] = bt.stats["balance_short"]
                e_short[idx] = bt.stats["equity_short"]
                we_short[idx] = -abs(bt.stats["wallet_exposure_short"])
                be.line(x, b_short[idx], legend_label=f'{self.backtests.index(bt)}: {bt.exchange} {bt.symbol} {bt.sd} {bt.ed} short_balance',color=Category20_20[color_b], line_width=2, name=f'{self.backtests.index(bt)}: {bt.exchange} {bt.symbol} {bt.sd} {bt.ed} short_balance')
                be.line(x, e_short[idx], legend_label=f'{self.backtests.index(bt)}: {bt.exchange} {bt.symbol} {bt.sd} {bt.ed} short_equity',color=Category20_20[color_e], line_width=1, name=f'{self.backtests.index(bt)}: {bt.exchange} {bt.symbol} {bt.sd} {bt.ed} short_equity')
                we.line(x, we_short[idx], legend_label=f'{self.backtests.index(bt)}: {bt.exchange} {bt.symbol} {bt.sd} {bt.ed} wallet_exposure_short',color=Category20_20[color_b], line_width=1, name=f'{self.backtests.index(bt)}: {bt.exchange} {bt.symbol} {bt.sd} {bt.ed} wallet_exposure_short')
        if be.legend:
            be.yaxis[0].formatter = NumeralTickFormatter(format="$ 0")
            be_leg = be.legend[0]
            be.add_layout(be_leg,'above')
            be.add_tools(hover_be)
            we.add_tools(hover_we)
            be.legend.location = "top_left"
            be.legend.click_policy="hide"
            st.bokeh_chart(be, use_container_width=True)
        if we.legend:
            we_leg = we.legend[0]
            we.add_layout(we_leg,'above')
            we.legend.location = "top_left"
            we.legend.click_policy="hide"
            st.bokeh_chart(we, use_container_width=True)

        idx = 0
        col_r1, col_r2 = st.columns([1,1]) 
        for bt in self.backtests:
            if bt.selected:
                idx +=1
                if idx == 3: idx = 1
                if idx == 1:
                    with col_r1:
                        st.write(f'{self.backtests.index(bt)}: {bt.exchange} {bt.symbol} {bt.sd} {bt.ed}')
                        st.code(bt.result_txt)
                        st.code(bt.config)
                if idx == 2:
                    with col_r2:
                        st.write(f'{self.backtests.index(bt)}: {bt.exchange} {bt.symbol} {bt.sd} {bt.ed}')
                        st.code(bt.result_txt)
                        st.code(bt.config)


    def find_all(self):
        p = str(Path(f'{self.backtest_path}/*/*/plots/*/result.json'))
        found_bt = glob.glob(p, recursive=True)
        if found_bt:
            for p in found_bt:
                bt = BacktestResult(PurePath(p).parent)
                self.backtests.append(bt)
                if bt.symbol not in self.symbols:
                    self.symbols.append(bt.symbol)
                if bt.exchange not in self.exchanges:
                    self.exchanges.append(bt.exchange)

    def match_item(self, item: BacktestItem = None):
        long = json.loads(item.config)["long"]
        short = json.loads(item.config)["short"]
        p = str(Path(f'{self.backtest_path}/{item.exchange.name}*/{item.symbol}/plots/*/result.json'))
        found_bt = glob.glob(p, recursive=True)
        if found_bt:
            for p in found_bt:
                bt = BacktestResult(PurePath(p).parent)
                if (
                    item.symbol == bt.symbol
                    and item.sd == bt.sd
                    and item.ed == bt.ed
                    and item.sb == bt.sb
                    and item.market_type == bt.market_type
                    and item.exchange.name == bt.exchange
                    and long["ema_span_0"] == bt.long["ema_span_0"]
                    and long["ema_span_1"] == bt.long["ema_span_1"]
                    and long["enabled"] == bt.long["enabled"]
                    and long["min_markup"] == bt.long["min_markup"]
                    and long["markup_range"] == bt.long["markup_range"]
                    and long["n_close_orders"] == bt.long["n_close_orders"]
                    and long["wallet_exposure_limit"] == bt.long["wallet_exposure_limit"]
                    and short["ema_span_0"] == bt.short["ema_span_0"]
                    and short["ema_span_1"] == bt.short["ema_span_1"]
                    and short["enabled"] == bt.short["enabled"]
                    and short["min_markup"] == bt.short["min_markup"]
                    and short["markup_range"] == bt.short["markup_range"]
                    and short["n_close_orders"] == bt.short["n_close_orders"]
                    and short["wallet_exposure_limit"] == bt.short["wallet_exposure_limit"]
                ):
                    self.backtests.append(bt)
            if not self.backtests:
                st.write("Backtest result not found. Please Run it again")
                item.remove_log()
        else:
            st.write("Backtest result not found. Please Run it again")
            item.remove_log()


    def match_config(self, symbol, config: json = None):
        long = json.loads(config)["long"]
        short = json.loads(config)["short"]
        p = str(Path(f'{self.backtest_path}/*/{symbol}/plots/*/result.json'))
        found_bt = glob.glob(p, recursive=True)
        if found_bt:
            for p in found_bt:
                bt = BacktestResult(PurePath(p).parent)
                if (
                    symbol == bt.symbol
                    and long["ema_span_0"] == bt.long["ema_span_0"]
                    and long["ema_span_1"] == bt.long["ema_span_1"]
                    and long["enabled"] == bt.long["enabled"]
                    and long["min_markup"] == bt.long["min_markup"]
                    and long["markup_range"] == bt.long["markup_range"]
                    and long["n_close_orders"] == bt.long["n_close_orders"]
                    and long["wallet_exposure_limit"] == bt.long["wallet_exposure_limit"]
                    and long["backwards_tp"] == bt.long["backwards_tp"]
                    and short["ema_span_0"] == bt.short["ema_span_0"]
                    and short["ema_span_1"] == bt.short["ema_span_1"]
                    and short["enabled"] == bt.short["enabled"]
                    and short["min_markup"] == bt.short["min_markup"]
                    and short["markup_range"] == bt.short["markup_range"]
                    and short["n_close_orders"] == bt.short["n_close_orders"]
                    and short["wallet_exposure_limit"] == bt.short["wallet_exposure_limit"]
                    and short["backwards_tp"] == bt.short["backwards_tp"]
                ):
                    self.backtests.append(bt)
                    if bt.symbol not in self.symbols:
                        self.symbols.append(bt.symbol)
                    if bt.exchange not in self.exchanges:
                        self.exchanges.append(bt.exchange)

def main():
    bt = BacktestQueue()
    while True:
        bt.load()
        for item in bt.items:
            while bt.running() == bt.cpu:
                time.sleep(5)
            bt.pb_config.read('pbgui.ini')
            if not eval(bt.pb_config.get("backtest", "autostart")):
                return
            if item.status() == "not started":
                print(f'{datetime.datetime.now().isoformat(sep=" ", timespec="seconds")} Backtesting {item.file} started')
                item.run()
        time.sleep(60)

if __name__ == '__main__':
    main()
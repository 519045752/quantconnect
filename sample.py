# region imports
from AlgorithmImports import *
from datetime import *
from QuantConnect.Statistics import TradeBuilder, FillGroupingMethod, FillMatchingMethod
from QuantConnect import Chart, Series, SeriesType


# endregion


class SQQQShortWithCollar(QCAlgorithm):
    # 核心策略类：通过波动率分层做空杠杆ETF，并辅以期权领口策略保护

    def initialize(self):
        # 策略初始化函数，在回测/实盘开始时执行一次

        # === 基础 ===
        # 禁用强平（注释掉了，实际未启用）
        # self.portfolio.margin_call_model = MarginCallModel.NULL
        self.set_start_date(2020, 4, 1)  # 设置回测起始日期
        # self.set_end_date(2018, 12, 31)  # 结束日期被注释掉了
        self.set_cash(3_000_000)  # 设置初始资金为300万美元
        self.add_equity("SPY", Resolution.MINUTE)  # 添加SPY作为基准，分钟级数据
        self.set_security_initializer(self._custom_security_initializer)  # 设置证券初始化器（手续费模型）

        # === 日额度 ===
        self.daily_limit_ratio = 0.30  # 每日新增做空额度上限占净资产的比例（30%）
        self.daily_limit = self.portfolio.total_portfolio_value * self.daily_limit_ratio  # 计算每日额度上限
        self.daily_used = 0.0  # 初始化当日已使用额度

        # === 多标的 σ 配置 ===
        # 配置不同杠杆ETF的波动率分层参数和仓位限制
        self.layer_cfg = {
            'SQQQ': {
                'sigma0': 1.83, 'sigma1': 3.72, 'sigma2': 7.50,  # 三层波动率阈值（百分比）
                'volume': 0.10,  # 满仓层（第三层）时目标仓位占净资产比例（10%）
                'max_short_ratio': 0.30  # 单标的最大做空名义上限占净资产比例（30%）
            },
            'SOXS': {
                'sigma0': 3.18, 'sigma1': 6.51, 'sigma2': 13.20,
                'volume': 0.10,
                'max_short_ratio': 0.30
            },
            'SPXU': {
                'sigma0': 1.59, 'sigma1': 3.24, 'sigma2': 6.54,
                'volume': 0.10,
                'max_short_ratio': 0.30
            },
            'SBIT': {
                'sigma0': 4.10, 'sigma1': 8.16, 'sigma2': 16.28,
                'volume': 0.10,
                'max_short_ratio': 0.2  # 比特币相关ETF上限较低（20%）
            },
            # 以下标的被注释掉了，暂时不交易
            #            'LABD': {
            #                'sigma0': 3.39, 'sigma1': 6.72, 'sigma2': 13.38,
            #                'volume': 0.10,
            #                'max_short_ratio': 0.2
            #            },
            #            'TZA': {
            #                'sigma0': 2.31, 'sigma1': 4.59, 'sigma2': 9.15,
            #                'volume': 0.10,
            #                'max_short_ratio': 0.2
            #            },
            'YANG': {
                'sigma0': 2.43, 'sigma1': 4.86, 'sigma2': 9.72,
                'volume': 0.10,
                'max_short_ratio': 0.2
            },
            # 以下标的的max_short_ratio使用默认值0.50
            # 'TMV':  {'sigma0': 1.50, 'sigma1': 2.94, 'sigma2': 5.82, 'volume': 0.10},
            # 'SVIX': {'sigma0': 2.38, 'sigma1': 4.66, 'sigma2': 9.22, 'volume': 0.10}
        }

        # === 交易记录结构 ===
        self.order_log = []  # 列表，记录每笔成交的详细信息
        self.position_tracker = {}  # 字典，跟踪每个标的的当前持仓数量

        # TradeBuilder：用于统计完整交易（平仓到平仓），按FIFO方式匹配
        tb = TradeBuilder(FillGroupingMethod.FLAT_TO_FLAT, FillMatchingMethod.FIFO)
        self.set_trade_builder(tb)  # 设置系统的TradeBuilder
        self.my_trade_builder = tb  # 同时保留自己的引用以便访问

        # === VIX配置 ===
        self.vix_threshold = 30.0  # VIX波动率指数的高波动阈值
        self.vix_high_volume = 0.40  # VIX高于阈值时的统一仓位放大比例（40%）

        # === 订阅VIX ===
        self.vix_symbol = None
        try:
            # 添加VIX指数数据，分钟级分辨率
            self.vix_symbol = self.add_index("VIX", Resolution.MINUTE).symbol
        except Exception as e:
            self.debug(f"[INIT] VIX index subscribe failed: {e}")  # 订阅失败时记录调试信息

        # === 期权参数（Collar领口策略）===
        self.option_trigger_pct = 3.0  # 标的当日涨幅触发collar策略的百分比（3%）
        self.option_cooldown_days = 1  # collar策略冷却期天数（全局共享）
        self.last_option_date = None  # 记录上次执行collar策略的日期

        # === 订阅标的 ===
        self.pool_symbols = {}  # 字典：ticker -> Symbol（股票）
        self.option_symbols = {}  # 字典：ticker -> canonical option Symbol（期权）
        self.preclose = {}  # 字典：Symbol -> 昨日收盘价

        # 为配置中的每个标的订阅股票和期权数据
        for t in self.layer_cfg.keys():
            try:
                # 订阅股票（使用RAW价格模式，避免调整）
                equity = self.add_equity(
                    t,
                    Resolution.MINUTE,
                    data_normalization_mode=DataNormalizationMode.RAW
                )
                self.pool_symbols[t] = equity.symbol  # 保存股票Symbol

                # 订阅期权并保存canonical symbol
                option = self.add_option(t, Resolution.MINUTE)  # 添加期权，分钟级数据
                # 设置期权过滤器：包含周期权，执行价上下10档，到期日14-45天
                option.set_filter(
                    lambda u: u.include_weeklys().strikes(-10, 10).expiration(14, 45)
                )
                self.option_symbols[t] = option.symbol  # 保存期权Symbol
            except Exception as e:
                self.debug(f"[INIT] {t} subscribe failed: {e}")  # 订阅失败时记录

        # === 调度 ===
        # 安排每日开盘后记录标的的昨日收盘价
        self.schedule.on(
            self.date_rules.every_day('SPY'),  # 每个SPY交易日
            self.time_rules.after_market_open('SPY', 0),  # SPY开盘后立即
            self.record_pool_pre_close  # 执行函数
        )

        # 安排每日开盘后重置日额度
        self.schedule.on(
            self.date_rules.every_day('SPY'),
            self.time_rules.after_market_open('SPY', 0),
            self.DailyRe
        )

        # 安排每日收盘前5分钟检查并执行10%止盈
        self.schedule.on(
            self.date_rules.every_day('SPY'),
            self.time_rules.before_market_close('SPY', 5),
            self.CloseShortEquityProfits10
        )

        # === 自定义图表：价格 + 交易点位 ===
        trade_chart = Chart("Trades")  # 创建名为"Trades"的图表
        for t in self.layer_cfg.keys():
            trade_chart.add_series(Series(f"{t}_Price", SeriesType.Line, 0))  # 价格线
            trade_chart.add_series(Series(f"{t}_Entry", SeriesType.Scatter, 0))  # 开仓点
            trade_chart.add_series(Series(f"{t}_Exit", SeriesType.Scatter, 0))  # 平仓点
            trade_chart.add_series(Series(f"{t}_SellPut", SeriesType.Scatter, 0))  # 卖出认沽期权点
            trade_chart.add_series(Series(f"{t}_BuyCall", SeriesType.Scatter, 0))  # 买入认购期权点
        self.add_chart(trade_chart)  # 添加图表到算法

    # ---------- 开盘维护：记录昨收 ----------
    def record_pool_pre_close(self):
        """每日开盘后记录每个标的的昨日收盘价"""
        for t, sym in self.pool_symbols.items():  # 遍历所有标的
            try:
                # 获取该标的最近1天的日线数据
                hist = self.history(sym, 1, Resolution.DAILY)
                if hist is None or hist.empty:  # 检查数据是否有效
                    continue

                # 从历史数据中提取收盘价（处理不同的列名格式）
                if 'close' in hist.columns:
                    c = float(hist['close'].iloc[-1])  # 小写列名
                elif 'Close' in hist.columns:
                    c = float(hist['Close'].iloc[-1])  # 大写列名
                else:
                    c = float(getattr(hist.iloc[-1], 'close'))  # 使用属性访问

                if c == c and c > 0:  # 检查是否为有效正数（不是NaN）
                    self.preclose[sym] = c  # 保存到preclose字典
            except Exception:
                continue  # 异常时跳过该标的

    # ---------- 每日重置日额度 ----------
    def DailyRe(self):
        """每日重置每日交易额度"""
        nav = max(self.portfolio.total_portfolio_value, 1e-9)  # 获取当前净资产，确保大于0
        self.daily_limit = nav * self.daily_limit_ratio  # 重新计算每日额度上限
        self.daily_used = 0.0  # 重置当日已使用额度

    # ---------- 主循环 ----------
    def on_data(self, data: Slice):
        """每分钟数据到达时的主处理函数"""
        # 先画价格线（每分钟一笔）
        for t, sym in self.pool_symbols.items():  # 遍历所有标的
            sec = self.securities.get(sym, None)  # 获取证券对象
            if sec is not None and sec.price and sec.price > 0:  # 检查价格有效
                self.plot("Trades", f"{t}_Price", sec.price)  # 绘制价格到图表

        # 每15分钟检查一次信号（分钟数能被15整除时）
        if self.time.minute % 15 != 0:
            return  # 不是15分钟的倍数时直接返回

        # 执行做空逻辑
        self.ShortEquityBySigma()

        # Collar期权保护（当前被注释掉了）
        # self.CheckCollarOption(data)

    # ---------- 做空持仓10%止盈 ----------
    def CloseShortEquityProfits10(self):
        """收盘前检查并平仓盈利超过10%的空头头寸"""
        for sec in list(self.securities.values()):  # 遍历所有证券
            if sec.type != SecurityType.EQUITY:  # 只处理股票类型
                continue

            h = self.portfolio[sec.symbol]  # 获取持仓信息
            qty = h.quantity  # 持仓数量
            if qty >= 0:  # 只处理空头头寸（数量为负）
                continue

            up = h.unrealized_profit_percent  # 未实现盈亏百分比
            if up is None:  # 检查是否有未实现盈亏数据
                continue

            # 空头盈利+10%以上平仓（对于空头，价格上涨亏损，价格下跌盈利）
            if up >= 0.10:  # up为正表示盈利
                self.market_order(sec.symbol, -qty, tag="COVER_TP10")  # 市价平仓（买入平空）
                self.debug(  # 记录调试信息
                    f"[SHORT TP 10%] {sec.symbol.value} up={up:.2%} -> cover {abs(qty)}"
                )

    # ---------- σ分层做空逻辑（3层，带单标的总持仓上限） ----------
    def ShortEquityBySigma(self):
        """根据波动率分层执行做空交易"""
        total_value = max(self.portfolio.total_portfolio_value, 1e-9)  # 当前净资产
        remaining_day_cap = max(self.daily_limit - self.daily_used, 0.0)  # 剩余日额度

        # 获取当前VIX水平
        vix_level = float('nan')  # 初始化为NaN
        try:
            if self.vix_symbol and self.vix_symbol in self.securities:
                vix_level = self.securities[self.vix_symbol].price  # 获取VIX价格
        except Exception:
            pass  # 获取失败时保持NaN

        # 遍历所有配置的标的
        for t, sym in self.pool_symbols.items():
            conf = self.layer_cfg.get(t)  # 获取该标的的配置
            if not conf:  # 如果没有配置则跳过
                continue

            # 获取昨收与当前价
            pre = self.preclose.get(sym, None)  # 昨日收盘价
            if not pre or pre <= 0:  # 检查昨收是否有效
                continue

            price = self.securities[sym].price  # 当前价格
            if not price or price <= 0:  # 检查当前价是否有效
                continue

            # 计算当日涨跌幅（%）
            diff = (price - pre) / pre * 100.0

            # sigma0以下不做（第一层波动率阈值以下不交易）
            if diff < conf['sigma0']:
                continue

            # VIX动态调整volume
            base_volume = conf['volume']  # 基础仓位比例
            effective_volume = self._effective_volume(base_volume, vix_level)  # 根据VIX调整后的仓位

            # 三层分仓逻辑：
            # L1: sigma0 ～ sigma1   -> 1/3 * effective_volume
            # L2: sigma1 ～ sigma2   -> 2/3 * effective_volume
            # L3: >= sigma2          -> 1.0 * effective_volume
            if diff < conf['sigma1']:  # 第一层
                target_frac = effective_volume / 3.0
                layer = 1
            elif diff < conf['sigma2']:  # 第二层
                target_frac = effective_volume * 2.0 / 3.0
                layer = 2
            else:  # 第三层（满仓层）
                target_frac = effective_volume
                layer = 3

            # 分层对应的"理论目标名义"价值
            target_value = total_value * target_frac

            # 当前空头名义价值（单标的）
            h = self.portfolio[sym]  # 获取持仓
            current_short_value = 0.0
            if h.quantity < 0 and price > 0:  # 有空头持仓
                current_short_value = abs(h.quantity) * price  # 计算当前空头名义价值

            # ===== 单标的总空头名义上限 =====
            # 优先从配置里拿max_short_ratio，没配就默认50% NAV
            max_short_ratio = conf.get('max_short_ratio', 0.50)  # 获取配置或使用默认值
            max_short_value = total_value * max_short_ratio  # 计算最大允许空头价值

            # 在单标的上限下还能再加多少名义价值
            remaining_symbol_cap = max(0.0, max_short_value - current_short_value)
            if remaining_symbol_cap <= 0:
                # 这只已经达到/超过上限，不再加仓
                continue

            # 分层目标下需要新增的名义价值
            add_value = max(0.0, target_value - current_short_value)
            if add_value <= 0:
                # 已经达到分层目标
                continue

            # 同时受"分层目标"和"单标的上限"约束
            add_value = min(add_value, remaining_symbol_cap)
            if add_value <= 0:
                continue

            # ===== 再叠加"当日日新增名义上限" =====
            shares_by_target = int(add_value // price)  # 根据目标价值计算股数
            shares_by_daycap = int(remaining_day_cap // price)  # 根据日额度计算股数
            shares = max(0, min(shares_by_target, shares_by_daycap))  # 取两者最小值

            if shares <= 0:  # 没有可交易的股数
                continue

            # 下单做空，带上层级tag
            self.market_order(sym, -shares, tag=f"SHORT_SIGMA_L{layer}")  # 市价卖出做空

            spend_notional = shares * price  # 计算使用的名义价值
            self.daily_used += spend_notional  # 更新当日已使用额度
            remaining_day_cap = max(self.daily_limit - self.daily_used, 0.0)  # 重新计算剩余额度

            # 记录详细的调试信息
            self.debug(
                f"[SHORT] {t} +{diff:.2f}% -> L{layer} tgt={target_frac:.3f}*NAV "
                f"| cur_short=${current_short_value:.0f} | add≈${add_value:.0f} "
                f"| symbol_cap=${max_short_value:.0f} "
                f"| sell {shares} sh @ ~{price:.2f} "
                f"| used_day=${self.daily_used:.0f}/${self.daily_limit:.0f} "
                f"| qty={self.portfolio[sym].quantity} "
                f"| vix={vix_level:.2f} vol={effective_volume:.2f}"
            )

    # ---------- 所有订单回调：记录 + 图上打点 ----------
    def on_order_event(self, order_event: OrderEvent) -> None:
        """订单事件回调函数，处理订单成交事件"""
        # 只关心有成交量的事件（fill_quantity不为0）
        if order_event.fill_quantity == 0:
            return

        sym = order_event.symbol  # 交易标的
        fill_qty = int(order_event.fill_quantity)  # 成交数量
        fill_price = float(order_event.fill_price)  # 成交价格
        direction = str(order_event.direction)  # 交易方向
        oid = order_event.order_id  # 订单ID

        # 从Order对象上拿Tag（OrderEvent自己没有tag）
        tag = ""
        try:
            order = self.Transactions.GetOrderById(oid)  # 通过订单ID获取订单对象
            if order is not None and order.Tag:
                tag = str(order.Tag)  # 获取订单标签
        except Exception:
            tag = ""

        sec = self.securities.get(sym, None)  # 获取证券对象
        asset_type = str(sec.type) if sec is not None else "Unknown"  # 资产类型

        # ---- 仓位变动前后（自己的tracker）----
        prev_qty = self.position_tracker.get(sym, 0)  # 交易前持仓
        new_qty = prev_qty + fill_qty  # 交易后持仓
        self.position_tracker[sym] = new_qty  # 更新跟踪器

        # 尝试从Portfolio读持仓（官方数据源）
        try:
            holding = self.portfolio[sym]  # 获取官方持仓数据
            pos_after = holding.quantity  # 交易后持仓数量
            avg_price_after = float(holding.average_price)  # 交易后平均价格
        except Exception:
            pos_after = new_qty  # 异常时使用自己的tracker数据
            avg_price_after = 0.0

        # ---- 写入内存log ----
        self.order_log.append({
            "time": self.time,  # 交易时间
            "symbol": sym.value,  # 标的代码
            "asset_type": asset_type,  # 资产类型
            "order_id": oid,  # 订单ID
            "tag": tag,  # 订单标签
            "direction": direction,  # 交易方向
            "fill_qty": fill_qty,  # 成交数量
            "fill_price": fill_price,  # 成交价格
            "position_after": pos_after,  # 交易后持仓
            "avg_price_after": avg_price_after  # 交易后平均成本
        })

        # 同时打到日志里一行（方便在线查看）
        self.debug(
            f"[ORDER] {self.time} {sym.value} {asset_type} "
            f"id={oid} tag={tag} dir={direction} "
            f"fill={fill_qty}@{fill_price:.4f} "
            f"pos={pos_after} avg={avg_price_after:.4f}"
        )

        # ---- 可视化：在Trades图上标记 ----
        # 1）标的股票：从0->非0视为开仓点，从非0->0视为平仓点
        if sec is not None and sec.type == SecurityType.EQUITY and sym in self.pool_symbols.values():
            ticker = sym.value  # 获取标的代码
            if prev_qty == 0 and new_qty != 0:
                # 开仓：从空仓到有持仓
                self.plot("Trades", f"{ticker}_Entry", fill_price)  # 标记开仓点
            elif prev_qty != 0 and new_qty == 0:
                # 平仓：从有持仓到空仓
                self.plot("Trades", f"{ticker}_Exit", fill_price)  # 标记平仓点

        # 2）期权：用tag识别Collar（不用去碰Symbol的OptionRight / Underlying）
        if tag.startswith("COLLAR_PUT_"):  # 卖出认沽期权
            ticker = tag.replace("COLLAR_PUT_", "")  # 从tag提取标的代码
            self.plot("Trades", f"{ticker}_SellPut", fill_price)  # 标记卖出认沽点

        elif tag.startswith("COLLAR_CALL_"):  # 买入认购期权
            ticker = tag.replace("COLLAR_CALL_", "")  # 从tag提取标的代码
            self.plot("Trades", f"{ticker}_BuyCall", fill_price)  # 标记买入认购点

    # ---------- 工具函数 ----------
    def _custom_security_initializer(self, security: Security) -> None:
        """自定义证券初始化器，设置手续费模型"""
        security.set_fee_model(ConstantFeeModel(0, "USD"))  # 设置零手续费模型

    def _effective_volume(self, base_volume: float, vix_level: float) -> float:
        """根据VIX调整单标的target volume"""
        try:
            # 检查VIX是否有效且高于阈值（vix_level == vix_level 用于检查NaN）
            if vix_level == vix_level and vix_level > self.vix_threshold:
                return float(self.vix_high_volume)  # 返回高波动率时的统一仓位
        except Exception:
            pass  # 异常时返回基础仓位
        return float(base_volume)  # 默认返回基础仓位

    def on_end_of_algorithm(self):
        """算法结束时执行的函数，输出最终统计信息"""
        # 最终净值
        self.debug(f"Final Portfolio Value: ${self.portfolio.total_portfolio_value:,.2f}")

        # === 1）订单明细：每一笔fill（含collar期权腿）===
        self.debug(  # 输出CSV格式的标题行
            "ORDER_LOG,time,symbol,asset_type,order_id,tag,"
            "direction,fill_qty,fill_price,position_after,avg_price_after"
        )

        # 遍历所有订单记录，逐行输出
        for r in self.order_log:
            self.debug(
                "ORDER_LOG," +
                f"{r['time']},{r['symbol']},{r['asset_type']},{r['order_id']},"  # noqa: E501
                f"{r['tag']},{r['direction']},{r['fill_qty']},{r['fill_price']:.4f},"  # noqa: E501
                f"{r['position_after']},{r['avg_price_after']:.4f}"
            )

        # === 2）TradeBuilder统计的完整round-trip交易 ===
        trades = []
        try:
            trades = self.my_trade_builder.closed_trades  # 获取所有已平仓交易
        except Exception:
            pass  # 异常时使用空列表

        # 输出交易统计的CSV标题行
        self.debug(
            "TRADE_LOG,symbol,direction,quantity,entry_time,entry_price,"
            "exit_time,exit_price,profit_loss,total_fees,mae,mfe,end_drawdown,duration"
        )

        # 遍历所有交易，逐行输出详细信息
        for tr in trades:
            self.debug(
                "TRADE_LOG," +
                f"{tr.symbol.value},{tr.direction},{tr.quantity},"
                f"{tr.entry_time},{tr.entry_price:.4f},"
                f"{tr.exit_time},{tr.exit_price:.4f},"
                f"{tr.profit_loss:.2f},{tr.total_fees:.2f},"
                f"{tr.mae:.2f},{tr.mfe:.2f},{tr.end_trade_drawdown:.2f},{tr.duration}"
            )


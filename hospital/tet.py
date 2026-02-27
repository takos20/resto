            bills_today = Bills.objects.filter(
                createdAt__range=[today_start, today_end],
                deleted=False
            )
            bills_unpaid_today = Bills.objects.filter(
                createdAt__range=[today_start, today_end],
                deleted=False
            ).aggregate(Sum('balance')
            )['balance__sum']
            bills_prev = Bills.objects.filter(
                createdAt__range=[prev_start, prev_end],
                deleted=False
            )

            bills_month = Bills.objects.filter(
                createdAt__range=[startdate, enddate],
                deleted=False
            ).aggregate(Sum('amount_paid')
            )['amount_paid__sum']

            bills_unpaid_month = Bills.objects.filter(
                createdAt__range=[startdate, enddate],
                deleted=False
            ).aggregate(Sum('balance')
            )['balance__sum']

            bills_prev_month = Bills.objects.filter(
                createdAt__range=[start_day_of_prev_month, last_day_of_prev_month],
                deleted=False
            ).aggregate(Sum('amount_paid')
            )['amount_paid__sum']

            bills_prev_unpaid_month = Bills.objects.filter(
                createdAt__range=[start_day_of_prev_month, last_day_of_prev_month],
                deleted=False
            ).aggregate(Sum('balance')
            )['balance__sum']


            settlements_today = PatientSettlement.objects.filter(
                createdAt__range=[today_start, today_end],
                deleted=False
            )
            settlements_previous = PatientSettlement.objects.filter(
                            createdAt__range=[prev_start, prev_end],
                            deleted=False
                        )

            cash_today = Cash_movement.objects.filter(
                createdAt__range=[today_start, today_end],
                deleted=False
            )
            cash_previous_today = Cash_movement.objects.filter(
                createdAt__range=[prev_start, prev_end],
                deleted=False
            )
            sales_today = bills_today.aggregate(Sum('net_payable')
            )['net_payable__sum']
            sales_prev = bills_prev.aggregate(Sum('net_payable'),
            )['net_payable__sum']
            settlement_today = settlements_today.aggregate(Sum('amount_paid')
            )['amount_paid__sum']
            settlement_previous = settlements_previous.aggregate(Sum('amount_paid')
            )['amount_paid__sum']

            cash_types_today = cash_today.values(
                types=F('type')
            ).annotate(total=Sum('amount_movement'))

            cash_types_previous = cash_previous_today.values(
                types=F('type')
            ).annotate(total=Sum('amount_movement'))

            get_sum_month= Cash_movement.objects.filter(createdAt__range=[startdate, enddate], deleted=False).values(types=F('type')).annotate(
                total=Sum('amount_movement'))
            get_sum_previous_month= Cash_movement.objects.filter(createdAt__range=[start_day_of_prev_month, last_day_of_prev_month], deleted=False).values(types=F('type')).annotate(
                total=Sum('amount_movement'))
            
            get_cash = Cash.objects.filter(is_active=True, open_date__year=today.year, open_date__month=today.month,
                                        open_date__day=today.day).last()
            if get_cash is not None:
                cash_balance = get_cash.balance
            else:
                cash_balance = 0

            get_cash_previous = Cash.objects.filter(is_active=True, open_date__year=previous_day.year,
                                                    open_date__month=previous_day.month,
                                                    open_date__day=previous_day.day).last()
            if get_cash_previous is not None:
                previous_cash_balance = get_cash_previous.balance
            else:
                previous_cash_balance = 0


            get_sum_bills_month_margin = DetailsBills.objects.filter(createdAt__range=[startdate, enddate],
                                                                    deleted=False).exclude(
                bills=None).aggregate(
                Sum('margin'))            
            get_sum_bills_month_cost_production = DetailsBills.objects.filter(createdAt__range=[startdate, enddate],
                                                                        deleted=False).exclude(
                    bills=None).aggregate(
                Sum('cost_production'))['cost_production__sum']
            get_sum_bills_cost_production = DetailsBills.objects.filter(createdAt__range=[today_start, today_end],
                                                                        deleted=False).exclude(
                    bills=None).aggregate(
                Sum('cost_production'))['cost_production__sum']
            month_margin = get_sum_bills_month_margin['margin__sum']        
            get_sum_bills_month_tva = Bills.objects.filter(createdAt__range=[startdate, enddate],
                                                                    deleted=False).aggregate(
                Sum('tva'))
            month_tva = get_sum_bills_month_tva['tva__sum']

            get_sum_bills_previous_month_margin = DetailsBills.objects.filter(
                createdAt__range=[start_day_of_prev_month, last_day_of_prev_month], deleted=False).exclude(
                bills=None).aggregate(
                Sum('margin'))           
            get_sum_bills_previous_month_cost_production = DetailsBills.objects.filter(
                createdAt__range=[start_day_of_prev_month, last_day_of_prev_month], deleted=False).exclude(
                bills=None).aggregate(
                Sum('cost_production'))['cost_production__sum']
            
            get_sum_bills_previous_cost_production = DetailsBills.objects.filter(
                createdAt__range=[prev_start, prev_end], deleted=False).exclude(
                bills=None).aggregate(
                Sum('cost_production'))['cost_production__sum']
            previous_month_margin = get_sum_bills_previous_month_margin['margin__sum'] 

            get_sum_bills_previous_month_tva = Bills.objects.filter(
                createdAt__range=[start_day_of_prev_month, last_day_of_prev_month], deleted=False).aggregate(
                Sum('tva'))
            previous_month_tva = get_sum_bills_previous_month_tva['tva__sum']
            
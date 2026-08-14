from __future__ import annotations
import unittest
from orbit.application.rb2_long_cycle import aggregate_completed_4h, future_extrema, path_metrics, trend_series
from orbit.domain.calibration.r0_shortline import ShortlineCandle

MS=900_000
def rows(count, start=100.0, step=.1):
    return [ShortlineCandle(i*MS,(i+1)*MS-1,start+i*step,start+i*step+1,start+i*step-1,start+i*step,1) for i in range(count)]

class RB2LongCycleTests(unittest.TestCase):
    def test_completed_4h_only(self):
        self.assertEqual(len(aggregate_completed_4h(rows(33))),2)

    def test_future_extrema_and_smoothness_floor(self):
        data=rows(20); ex=future_extrema(data,8)
        result=path_metrics(data,1,"LONG",data[1].open,2,8,ex)
        self.assertEqual(result["mfe_bar"],8)
        self.assertEqual(result["mae_bar"],1)
        self.assertGreaterEqual(result["smoothness"],0)

    def test_trend_uses_360_prior_4h_bars(self):
        bars=[(i*14_400_000,100+i*.1) for i in range(400)]
        result=trend_series(bars)
        self.assertIsNone(result[359]["state"])
        self.assertEqual(result[360]["state"],"UP")

if __name__=="__main__": unittest.main()

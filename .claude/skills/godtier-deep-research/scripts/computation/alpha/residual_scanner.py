# -*- coding: utf-8 -*-
"""
残差Alpha扫描器 - 在预测误差中寻找Alpha

核心原理：可预测的部分被定价，Alpha存留在误差中
"""
import numpy as np
import json
import math
import sys

# IMP-02：scipy 在本环境未安装。改为可选导入 + numpy/math 回退实现，
# 使 L-1 残差 Alpha 层在无 scipy 时仍可降级运行（p 值用正态近似，精度略降但不致崩）。
try:
    from scipy import stats
    _HAS_SCIPY = True
except ImportError:
    _HAS_SCIPY = False

    class _Norm:
        """标准正态分布（math 实现，供 p 值正态近似）"""
        @staticmethod
        def cdf(x):
            return 0.5 * (1.0 + math.erf(x / math.sqrt(2.0)))
        @staticmethod
        def sf(x):
            return 1.0 - _Norm.cdf(x)

    class _StatsFallback:
        """scipy.stats 的最小 numpy/math 回退实现"""
        norm = _Norm()

        @staticmethod
        def ttest_1samp(resids, popmean):
            n = len(resids)
            arr = np.array(resids, dtype=float)
            mean = float(np.mean(arr))
            sd = float(np.std(arr, ddof=1)) if n > 1 else 0.0
            if sd == 0:
                return (0.0, 1.0)
            t = (mean - popmean) / (sd / math.sqrt(n))
            p = 2.0 * _Norm.sf(abs(t))  # 双尾正态近似
            return (float(t), float(p))

        @staticmethod
        def pearsonr(a, b):
            a = np.array(a, dtype=float); b = np.array(b, dtype=float)
            n = len(a)
            if n < 2:
                return (0.0, 1.0)
            ma, mb = float(np.mean(a)), float(np.mean(b))
            da, db = a - ma, b - mb
            denom = math.sqrt(float(np.sum(da * da)) * float(np.sum(db * db)))
            if denom == 0:
                return (0.0, 1.0)
            r = float(np.sum(da * db) / denom)
            t = r * math.sqrt((n - 2) / max(1e-12, 1 - r * r))
            p = 2.0 * _Norm.sf(abs(t))
            return (r, p)

        @staticmethod
        def skew(a):
            a = np.array(a, dtype=float)
            if len(a) < 3:
                return 0.0
            m = float(np.mean(a)); s = float(np.std(a, ddof=1))
            if s == 0:
                return 0.0
            return float(np.mean(((a - m) / s) ** 3))

        @staticmethod
        def kurtosis(a):
            a = np.array(a, dtype=float)
            if len(a) < 4:
                return 0.0
            m = float(np.mean(a)); s = float(np.std(a, ddof=1))
            if s == 0:
                return 0.0
            return float(np.mean(((a - m) / s) ** 4)) - 3.0

    stats = _StatsFallback()
    print("[warn] scipy 未安装，残差扫描器使用 numpy/math 正态近似回退"
          "（p 值精度略降）。建议 pip install scipy 以获得精确 t 分布。", file=sys.stderr)

class ResidualAlphaScanner:
    def __init__(self, actual, predicted, features=None):
        self.actual = np.array(actual, dtype=float)
        self.predicted = np.array(predicted, dtype=float)
        self.residuals = self.actual - self.predicted
        self.features = features or {}
    
    def systematic_bias(self):
        """残差是否有系统性偏差"""
        if len(self.residuals) < 3:
            return {'error': '样本量不足'}
        t_stat, p_value = stats.ttest_1samp(self.residuals, 0)
        return {
            'mean_residual': float(np.mean(self.residuals)),
            'std_residual': float(np.std(self.residuals)),
            't_statistic': float(t_stat),
            'p_value': float(p_value),
            'biased': bool(p_value < 0.05),
            'direction': 'underestimate' if np.mean(self.residuals) > 0 else 'overestimate',
            'alpha_per_period': float(np.mean(self.residuals)),
            'annualized_alpha': float(np.mean(self.residuals) * 252) if len(self.residuals) > 60 else None
        }
    
    def residual_autocorrelation(self, max_lag=10):
        """残差自相关（可预测性）"""
        results = []
        n = len(self.residuals)
        for lag in range(1, min(max_lag + 1, n // 2)):
            if n - lag < 2:
                break
            corr, p_val = stats.pearsonr(self.residuals[:-lag], self.residuals[lag:])
            results.append({
                'lag': lag,
                'correlation': float(corr),
                'p_value': float(p_val),
                'predictable': bool(p_val < 0.05 and abs(corr) > 0.1)
            })
        any_predictable = any(r['predictable'] for r in results)
        return {
            'lags': results,
            'any_predictable': any_predictable,
            'alpha_type': 'mean_reversion' if (results and results[0]['correlation'] < -0.1) else 'momentum' if (results and results[0]['correlation'] > 0.1) else 'none'
        }
    
    def regime_dependence(self, regimes):
        """不同regime下的残差"""
        regime_stats = {}
        for regime in set(regimes):
            mask = [r == regime for r in regimes]
            reg_res = self.residuals[mask]
            if len(reg_res) < 2:
                continue
            regime_stats[str(regime)] = {
                'mean': float(np.mean(reg_res)),
                'std': float(np.std(reg_res)),
                'skew': float(stats.skew(reg_res)),
                'kurtosis': float(stats.kurtosis(reg_res)),
                'count': int(len(reg_res))
            }
        # 找最大Alpha的regime
        if regime_stats:
            best_regime = max(regime_stats.items(), key=lambda x: abs(x[1]['mean']))
            return {
                'regimes': regime_stats,
                'best_alpha_regime': best_regime[0],
                'best_alpha_value': best_regime[1]['mean']
            }
        return {'regimes': regime_stats}
    
    def missing_factor_test(self):
        """遗漏变量检验"""
        if not self.features:
            return {'error': '未提供特征数据'}
        factor_loadings = {}
        for fname, fvalues in self.features.items():
            fv = np.array(fvalues, dtype=float)
            if len(fv) != len(self.residuals):
                continue
            corr, p_val = stats.pearsonr(self.residuals, fv)
            if p_val < 0.1:
                factor_loadings[fname] = {
                    'correlation': float(corr),
                    'p_value': float(p_val),
                    'r_squared': float(corr ** 2),
                    'interpretation': f'模型遗漏{fname}因子，可解释{corr**2*100:.1f}%的残差方差'
                }
        return {
            'missing_factors': factor_loadings,
            'n_factors_found': len(factor_loadings),
            'total_r_squared_explained': sum(f['r_squared'] for f in factor_loadings.values())
        }
    
    def tail_mispricing(self, threshold=2.0):
        """尾部事件误定价"""
        if len(self.residuals) < 10:
            return {'error': '样本量不足'}
        z_scores = (self.residuals - np.mean(self.residuals)) / (np.std(self.residuals) + 1e-10)
        tail_mask = np.abs(z_scores) > threshold
        n_tail = int(np.sum(tail_mask))
        if n_tail == 0:
            return {'tail_events': 0, 'alpha_opportunity': False}
        expected_freq = 2 * (1 - stats.norm.cdf(threshold))
        actual_freq = n_tail / len(self.residuals)
        return {
            'tail_events': n_tail,
            'tail_frequency_actual': float(actual_freq),
            'tail_frequency_expected': float(expected_freq),
            'fat_tail_ratio': float(actual_freq / expected_freq) if expected_freq > 0 else None,
            'tail_mean_residual': float(np.mean(self.residuals[tail_mask])),
            'tail_direction': 'underestimate' if np.mean(self.residuals[tail_mask]) > 0 else 'overestimate',
            'alpha_opportunity': bool(abs(np.mean(self.residuals[tail_mask])) > np.std(self.residuals)),
            'tail_alpha_magnitude': float(abs(np.mean(self.residuals[tail_mask])))
        }
    
    def full_report(self, regimes=None):
        """完整报告"""
        report = {
            'sample_size': len(self.residuals),
            'systematic_bias': self.systematic_bias(),
            'autocorrelation': self.residual_autocorrelation(),
            'tail_mispricing': self.tail_mispricing(),
            'missing_factors': self.missing_factor_test()
        }
        if regimes:
            report['regime_dependence'] = self.regime_dependence(regimes)
        
        # 综合Alpha评分
        alpha_score = 0
        if report['systematic_bias']['biased']:
            alpha_score += 30
        if report['autocorrelation']['any_predictable']:
            alpha_score += 25
        if report['tail_mispricing'].get('alpha_opportunity'):
            alpha_score += 25
        if isinstance(report['missing_factors'], dict) and report['missing_factors'].get('n_factors_found', 0) > 0:
            alpha_score += 20
        report['alpha_score'] = alpha_score
        report['alpha_grade'] = 'A' if alpha_score >= 70 else 'B' if alpha_score >= 50 else 'C' if alpha_score >= 30 else 'D'
        
        return report


# CLI接口
if __name__ == '__main__':
    import sys
    if len(sys.argv) < 3:
        print("Usage: python residual_scanner.py <actual_json> <predicted_json> [features_json]")
        sys.exit(1)
    
    actual = json.loads(sys.argv[1])
    predicted = json.loads(sys.argv[2])
    features = json.loads(sys.argv[3]) if len(sys.argv) > 3 else None
    
    scanner = ResidualAlphaScanner(actual, predicted, features)
    report = scanner.full_report()
    print(json.dumps(report, indent=2, ensure_ascii=False))

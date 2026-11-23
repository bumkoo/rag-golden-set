"""⑤ 내보내기: 골든 후보 → 바깥 시스템의 데이터셋 형식. 형식 하나에 어댑터 모듈 하나를 둔다."""

from golden_set.exporting.awx import write_awx1

# 형식 이름 → 쓰는 함수(candidates, path). cli export의 --format 선택지다.
EXPORTERS = {"awx1": write_awx1}

__all__ = ["EXPORTERS", "write_awx1"]

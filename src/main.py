"""실행 진입점.

  현장사진정리기.exe "폴더"            사진 정리
  현장사진정리기.exe --undo "폴더"     사진 정리 되돌리기
  현장사진정리기.exe --install         우클릭 메뉴 등록
  현장사진정리기.exe --uninstall       우클릭 메뉴 해제
"""
import os
import sys
from datetime import datetime

import config
import organizer
import ui


def run_organize(folder, cfg):
    targets, skipped = organizer.scan(folder, cfg)
    if not targets:
        ui.info("정리할 사진이 없어요.")
        return
    win = ui.Window(folder, "정리")
    win.run(lambda progress: organizer.organize(folder, cfg, targets, skipped, progress),
            ui.show_organize_result)


def run_undo(folder, cfg):
    run = organizer.last_run(folder, cfg)
    if not run or not run.get("items"):
        ui.info("되돌릴 정리 기록이 없어요.")
        return
    try:
        t = datetime.fromisoformat(run["time"])
        when = f"{t.month}월 {t.day}일 {t:%H:%M}"
    except (KeyError, ValueError, TypeError):
        when = "날짜 모름"
    if not ui.ask(f"최근 정리({when}, {len(run['items'])}장)를 되돌릴까요?\n\n"
                  f"줄인 사진은 휴지통으로 보내고, 원본을 제자리로 옮겨요."):
        return
    win = ui.Window(folder, "되돌리기")
    win.run(lambda progress: organizer.undo_last(folder, cfg, progress), ui.show_undo_result)


def main(argv):
    ui.enable_dpi()
    if not argv:
        ui.info("폴더를 우클릭한 뒤 '더 많은 옵션 표시' → '사진 정리'로 실행해 주세요.")
        return
    if argv[0] in ("--install", "--uninstall"):
        import registry
        registry.install() if argv[0] == "--install" else registry.uninstall()
        return

    undo = argv[0] == "--undo"
    folder_arg = argv[1] if undo and len(argv) > 1 else (None if undo else argv[0])
    if not folder_arg or not os.path.isdir(folder_arg):
        ui.error("폴더를 찾을 수 없어요.")
        return
    folder = os.path.abspath(folder_arg)
    cfg = config.load()
    try:
        with organizer.FolderLock(folder):
            run_undo(folder, cfg) if undo else run_organize(folder, cfg)
    except organizer.AlreadyRunning:
        ui.info("이 폴더는 지금 정리(또는 되돌리기) 중이에요.\n끝난 뒤 다시 실행해 주세요.")


if __name__ == "__main__":
    main(sys.argv[1:])

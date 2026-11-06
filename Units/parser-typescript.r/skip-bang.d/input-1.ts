/* Derived from https://github.com/universal-ctags/ctags/issues/4000#issuecomment-2116428681
 * submitted by @char01 */
class A {
  f() {
    let c = true;

    const d = {
      e() {},
    };

    const a = (b: unknown) => {
      if (!c) {}
    };

    d.e();
  }
}
